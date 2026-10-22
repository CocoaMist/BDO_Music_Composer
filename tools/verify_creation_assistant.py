"""Create synthetic authoring examples and verify the real editor I/O/renderers.

Runs offline, caps numerical work to two CPUs, and never reads a player corpus
or writes a game directory. All artifacts go to a new output directory.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import time
import wave


def limit_cpu() -> int:
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "2"
    if os.name == "nt":
        import ctypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetCurrentProcess.restype = ctypes.c_void_p
        api.GetProcessAffinityMask.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t))
        api.SetProcessAffinityMask.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
        current, system = ctypes.c_size_t(), ctypes.c_size_t()
        process = api.GetCurrentProcess()
        if not api.GetProcessAffinityMask(process, ctypes.byref(current), ctypes.byref(system)):
            raise OSError("cannot read process CPU affinity")
        chosen = sum([1 << i for i in range(64) if current.value & (1 << i)][:2])
        if not api.SetProcessAffinityMask(process, chosen):
            raise OSError("cannot set process CPU affinity")
        return chosen.bit_count()
    if hasattr(os, "sched_getaffinity"):
        selected = sorted(os.sched_getaffinity(0))[:2]
        os.sched_setaffinity(0, selected)
        return len(selected)
    return 2


def run(output: Path, cpu_count: int) -> None:
    import numpy as np
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    from bdo_codec import decode_score, encode_score
    from bdo_midi import BDO_INSTRUMENT_NAMES, Note, parse_midi
    from bdo_music_composer.audio.bdo_realtime_audio import BdoRealtimeAudioEngine
    from bdo_music_composer.core.conversion_settings import ConversionSettings
    from bdo_music_composer.creation.brief import CreationAction, CreationBrief, MusicalCharacter
    from bdo_music_composer.creation.workspace import CreationContext, build_creation_session, projected_tracks
    from bdo_music_composer.editor.arrangement_clip import project_track_notes
    from bdo_music_composer.editor.editor_models import TrackState
    from bdo_music_composer.editor.editor_import import TrackImportPresentation, prepare_midi_import, tracks_from_project_payload
    from bdo_music_composer.editor.pitch_transform import PitchTransformPlan
    from bdo_music_composer.editor.preview_midi_writer import build_filtered_midi_bytes
    from bdo_music_composer.export.export_workflow import ExportRequest, freeze_export_tracks, prepare_export
    from bdo_music_composer.project.project_persistence import AutosaveRequest, ProjectMetadataSnapshot, freeze_project_tracks, write_autosave
    from bdo_music_composer.project.project_schema import CURRENT_PROJECT_SCHEMA
    from bdo_music_composer.ui.dialogs.creation_assistant_dialog import CreationAssistantDialog
    from bdo_music_composer.ui.i18n import install_localizer
    from bdo_music_composer.ui.main_window import MidiToBdoWindow

    app = QApplication.instance() or QApplication([])
    # Qt's offscreen Windows plugin has no system font database. Register the
    # installed font for this verification process only; do not copy/bundle it.
    if not QFontDatabase.families() and os.name == "nt":
        font_dir = Path(os.environ.get("WINDIR", "C:/Windows"))/"Fonts"
        for name in ("msyh.ttc", "segoeui.ttf", "seguisym.ttf", "segmdl2.ttf", "SegoeIcons.ttf"):
            font_path = font_dir/name
            if font_path.is_file():
                assert QFontDatabase.addApplicationFont(str(font_path)) >= 0
        app.setFont(QFont("Microsoft YaHei UI", 9))
    install_localizer(app, "zh_CN")
    presentation = TrackImportPresentation(("#d88c6f",), lambda i: BDO_INSTRUMENT_NAMES[i], str, lambda: "Drums", lambda i: f"Track {i}")
    evidence = {"cpu_count": cpu_count, "examples": [], "game_listening_verified": False}
    index_rows = []

    def link(label: str, path: Path) -> str:
        return f"[{label}](<{path.resolve().as_posix()}>)"

    def render(tracks, path):
        engine = BdoRealtimeAudioEngine(None, {"preview_mode": "generic"})
        engine._sample_rate = 24000
        try:
            prepared = engine._prepare_procedural_project(projected_tracks(tracks), 0, 0, 0, None)
            engine._commit_project(*prepared, start_ms=0)
            engine._playing = True
            frames = engine._duration_frames + 2400
            blocks = [engine._render_locked(1024).copy() for _ in range((frames+1023)//1024)]
            samples = np.concatenate(blocks)[:frames]
            peak = float(np.max(np.abs(samples)))
            assert 0 < peak < 1, peak
            pcm = np.round(samples * 32767).astype("<i2")
            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(2)
                stream.setsampwidth(2)
                stream.setframerate(24000)
                stream.writeframes(pcm.tobytes())
            return {"seconds": len(samples)/24000, "peak": peak, "events": len(prepared[0])}
        finally:
            engine.stop()

    def deliver(name, tracks, input_tracks=None):
        folder = output / name
        folder.mkdir()
        midi_path = folder / "建议.mid"
        midi_path.write_bytes(build_filtered_midi_bytes(tracks,120,4))
        parsed = parse_midi(midi_path,apply_sustain=False)
        expected = [n for t in tracks for n in project_track_notes(t)]
        assert sum(len(g[0]) for g in parsed[2]) == len(expected)
        request = ExportRequest(freeze_export_tracks(tracks),120,4,folder/"unused", "Synthetic",123,
            ConversionSettings.bdo_import_defaults(),PitchTransformPlan(0),0,0,None,folder/"unused-game")
        payload = prepare_export(request).data
        score = decode_score(payload)
        actual = Counter((n.pitch,n.velocity_a,n.start_ms,n.duration_ms,n.ntype) for g in score.groups for t in g.tracks for n in t.notes)
        assert actual == Counter(tuple(n) for n in expected)
        assert encode_score(score)==payload
        assert all(not g.tracks[-1].notes for g in score.groups)
        metadata = ProjectMetadataSnapshot.capture(schema_version=CURRENT_PROJECT_SCHEMA,
            output_name=name,owner_id=0,reason="synthetic creation example",bpm=120,time_signature=4,
            conversion_settings=ConversionSettings.bdo_import_defaults().to_payload(),pitch_transform=PitchTransformPlan(0).to_payload())
        project_path = write_autosave(AutosaveRequest(folder,metadata,freeze_project_tracks(tracks)))
        restored = tracks_from_project_payload(json.loads(project_path.read_text(encoding="utf-8")),presentation)
        assert [project_track_notes(t) for t in restored] == [project_track_notes(t) for t in tracks]
        audio = render(tracks,folder/"建议.wav")
        if input_tracks:
            (folder/"输入.mid").write_bytes(build_filtered_midi_bytes(input_tracks,120,4))
            render(input_tracks,folder/"输入.wav")
        evidence["examples"].append({"name":name,"notes":len(expected),"midi_import":True,"bdo_roundtrip":True,"project_restore":True,"audio":audio})
        original = link("原稿",folder/"输入.wav") if input_tracks else "—"
        index_rows.append(f"| {name[3:]} | {link('打开工程',project_path)} | {original} | {link('试听建议',folder/'建议.wav')} | {link('MIDI',midi_path)} |")
        print(json.dumps({"verified":name,"notes":len(expected)},ensure_ascii=False),flush=True)

    drafts = []
    for i, (character, name) in enumerate(((MusicalCharacter.LYRICAL,"01_抒情草稿"),(MusicalCharacter.LIGHT,"02_轻快草稿"),(MusicalCharacter.DRIVING,"03_有力草稿"))):
        value = build_creation_session(CreationContext.capture([],120,4),CreationBrief(CreationAction.DRAFT,character,variant=i))
        keys = frozenset({"melody","harmony","bass"} | ({"drums"} if i else set()))
        tracks = value.materialize(keys)
        drafts.append(tracks)
        deliver(name,tracks)
    source_path = output/"synthetic_melody.mid"
    melody = deepcopy(drafts[0][0])
    melody.notes = [n._replace(vel=80) for n in melody.notes]
    source_path.write_bytes(build_filtered_midi_bytes([melody],120,4))
    imported = prepare_midi_import(source_path,ConversionSettings.bdo_import_defaults(),presentation)
    sources = list(imported.tracks)
    context = CreationContext.capture(sources,imported.bpm,imported.time_signature)
    accompaniment = build_creation_session(context,CreationBrief(CreationAction.ACCOMPANY,MusicalCharacter.LIGHT,source_track_id=sources[0].track_id))
    deliver("04_旋律到伴奏",accompaniment.materialize(frozenset({"harmony","bass"})),sources)
    expression = build_creation_session(context,CreationBrief(CreationAction.EXPRESS,MusicalCharacter.LIGHT,source_track_id=sources[0].track_id,rewrite_velocity=True,shape_durations=True))
    deliver("05_导入MIDI的表达",expression.materialize(frozenset({"expression"})),sources)
    low_quality = [TrackState(1,[Note(p,80,i*500.,420.,0) for i,p in enumerate((100,103,105,103,100,98,96,100))],0,False,"Synthetic high register",17)]
    adaptation = build_creation_session(CreationContext.capture(low_quality,120,4),CreationBrief(CreationAction.ADAPT,source_track_id=1,melody_instrument=11))
    deliver("06_游戏乐器适配",adaptation.materialize(frozenset({"adaptation"})),low_quality)

    window = MidiToBdoWindow()
    window.tracks = []
    window.bpm, window.bpm_override, window.time_sig, window.time_sig_denominator = 120,0,4,4
    window._autosave_project = lambda *args, **kwargs: None
    window._refresh_tracks()
    window.resize(1440,900)
    window._show_workspace()
    window.show()
    app.processEvents()
    assert window.toolbar_creation_btn.isVisible() and window.toolbar_creation_btn.isEnabled()
    interacted, failures = [], []

    def use_assistant():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog,CreationAssistantDialog)
            dialog.generate_button.click()
            deadline = time.monotonic()+30
            while dialog.worker is not None and time.monotonic()<deadline:
                QTest.qWait(10)
            assert dialog.worker is None and dialog.sessions, dialog.status_label.text()
            app.processEvents()
            assert dialog.grab().save(str(output/"创作助手界面.png"))
            assert dialog.apply_button.isEnabled()
            interacted.append(True)
            dialog.apply_button.click()
        except Exception as exc:
            failures.append(repr(exc))
            if dialog is not None:
                dialog.reject()

    QTimer.singleShot(0,use_assistant)
    window.toolbar_creation_btn.click()
    assert interacted and not failures, failures
    assert window.tracks
    expected_tracks = deepcopy(window.tracks)
    window._undo_project()
    assert not window.tracks
    window._redo_project()
    assert window.tracks == expected_tracks
    app.processEvents()
    assert window.grab().save(str(output/"已应用工程.png"))
    evidence["ui_worker_preview_apply_undo_redo"] = True
    evidence["toolbar_entry_and_dialog_apply"] = True
    window.close()
    app.processEvents()
    (output/"verification.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    index_text = (
        "# 创作助手：从这里开始\n\n"
        "第一版已接入源码版主工具栏的“创作助手”。选择从空白写起、沿旋律添加伴奏、"
        "适配游戏乐器或调整演奏表达；生成后试听并勾选声部，应用后仍可继续编辑和撤销。\n\n"
        "下面六组是原创合成示例，可在程序中打开各自的 project.json，或导入 MIDI。"
        "音频由当前通用试听引擎生成，用来检查音乐内容和变化；游戏乐器的实际听感尚未验收。\n\n"
        "| 示例 | 可编辑工程 | 对照输入 | 建议音频 | MIDI |\n"
        "|---|---|---|---|---|\n" + "\n".join(index_rows) + "\n\n"
        "每组已检查 MIDI 解析、工程恢复、BDO 字段往返，以及音频非静音和峰值。"
        "界面已验证后台生成、应用和撤销/恢复。程序不会自动学习这些选择；"
        "当前是确定性规则基线。玩家风格学习、真实坏 MIDI 修复和自然语言协作见整体方案。\n\n"
        + link("整体方案",Path(__file__).resolve().parents[1]/"docs"/"CREATION_ASSISTANT_PLAN.md") + " · "
        + link("界面截图",output/"创作助手界面.png") + " · "
        + link("应用后的工程",output/"已应用工程.png") + " · "
        + link("验证记录",output/"verification.json") + "\n"
    )
    (output/"开始这里.md").write_text(index_text,encoding="utf-8")
    print(json.dumps({"complete":True,"output":str(output)},ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path)
    args = parser.parse_args()
    output = args.output or Path(__file__).resolve().parents[1]/"out"/"creation-assistant"/datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True,exist_ok=False)
    cpu_count = limit_cpu()
    os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    with tempfile.TemporaryDirectory() as temporary:
        os.environ["BDO_USER_DATA_DIR"] = temporary
        run(output,cpu_count)


if __name__ == "__main__":
    main()
