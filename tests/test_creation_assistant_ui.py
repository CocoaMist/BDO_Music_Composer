from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CreationAssistantUiTests(unittest.TestCase):
    def run_ui(self, script):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", BDO_USER_DATA_DIR=temp,
                       PYTHONIOENCODING="utf-8", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")
            result = subprocess.run([sys.executable,"-c",textwrap.dedent(script)],cwd=ROOT,env=env,
                                    capture_output=True,text=True,encoding="utf-8",timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_blank_to_candidate_partial_apply_undo_redo_and_live_locales(self):
        self.run_ui('''
            from copy import deepcopy
            from dataclasses import replace
            import time
            from PySide6.QtWidgets import QApplication, QDialog
            from PySide6.QtTest import QTest
            from bdo_music_composer.ui.main_window import MidiToBdoWindow
            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.dialogs.creation_assistant_dialog import CreationAssistantDialog
            from bdo_music_composer.editor.editor_models import TrackState, ArrangementClipState
            app = QApplication([])
            localizer = install_localizer(app,"zh_CN")
            window = MidiToBdoWindow()
            window.tracks = [TrackState(0,[],0,False,"empty",17,
                arrangement_clips=[ArrangementClipState("blank",0,2000,0,2000)])]
            window.bpm = 120
            window.bpm_override = 0
            window.time_sig = 4
            window.time_sig_denominator = 4
            window._refresh_tracks()
            saves = []
            window._autosave_project = lambda reason, immediate=False: saves.append(reason)
            before = deepcopy(window.tracks)
            revision = window.model_revision.value
            dialog = CreationAssistantDialog(window)
            dialog.show()
            app.processEvents()
            assert not dialog.feedback_box.isChecked()
            assert not dialog.apply_button.isEnabled()
            dialog.generate_button.click()
            deadline = time.monotonic()+20
            while dialog.worker is not None and time.monotonic()<deadline:
                QTest.qWait(10)
            assert dialog.worker is None
            assert len(dialog.sessions)==3, dialog.status_label.text()
            assert window.tracks==before
            assert dialog.apply_button.isEnabled(), dialog.status_label.text()
            dialog.candidate_combo.setCurrentIndex(1)
            dialog.part_checks["harmony"].setChecked(False)
            keys = dialog.selected_parts()
            assert keys==frozenset({"melody","bass"})
            chosen = dialog.current_session()
            for locale, title in (("en_US","Creation Assistant"),("ja_JP","創作アシスタント"),("ko_KR","창작 도우미"),("zh_TW","創作助手"),("zh_CN","创作助手")):
                localizer.set_language(locale)
                app.processEvents()
                assert dialog.windowTitle()==title,(locale,dialog.windowTitle())
                assert dialog.selected_parts()==keys
            dialog._accept_proposal()
            assert dialog.result()==QDialog.Accepted
            assert window._apply_creation_session(chosen,keys)
            assert len(window.tracks)==3
            # Adding a second piano part creates the normal instrument group;
            # the original music and Clip ownership stay unchanged.
            assert window.tracks[0]==replace(before[0],arrangement_group_id="game-instrument:17")
            assert window.model_revision.value>revision
            after = deepcopy(window.tracks)
            assert saves==["creation assistant"],saves
            try:
                window._apply_creation_session(chosen,keys)
                raise AssertionError("stale candidate reapplied")
            except ValueError: pass
            window._undo_project()
            assert window.tracks==before
            window._redo_project()
            assert window.tracks==after
            window.close()
            app.processEvents()
            app.quit()
        ''')

    def test_scaled_clip_and_instrument_mix_survive_apply_export_undo_redo(self):
        self.run_ui('''
            from copy import deepcopy
            from pathlib import Path
            from PySide6.QtWidgets import QApplication
            from bdo_midi import Note
            from bdo_codec import decode_score
            from bdo_music_composer.ui.main_window import MidiToBdoWindow
            from bdo_music_composer.creation.brief import CreationAction, CreationBrief
            from bdo_music_composer.creation.workspace import CreationContext, build_creation_session
            from bdo_music_composer.editor.editor_models import TrackState, ArrangementClipState
            from bdo_music_composer.editor.arrangement_clip import project_track_notes
            from bdo_music_composer.editor.pitch_transform import PitchTransformPlan
            from bdo_music_composer.core.conversion_settings import ConversionSettings
            from bdo_music_composer.export.export_workflow import ExportRequest, freeze_export_tracks, prepare_export
            app = QApplication([])
            window = MidiToBdoWindow()
            source = TrackState(1, [Note(60,80,0,300,0), Note(64,80,500,300,0),
                Note(67,80,4000,300,0)], 0, False, "source", 17, duration_scale=1.5,
                arrangement_clips=[ArrangementClipState("a",0,2000,0,2000),
                                   ArrangementClipState("b",4000,6000,4000,6000)])
            peer = TrackState(2, [Note(64,80,0,400,0)], 0, False, "peer", 11,
                bdo_track_volume=30, bdo_track_settings=(21,0,32,0,43,0,0,0))
            window.tracks = [source, peer]
            window.bpm, window.bpm_override = 120, 0
            window.time_sig, window.time_sig_denominator = 4, 4
            window._refresh_tracks()
            window._autosave_project = lambda *args, **kwargs: None
            before = deepcopy(window.tracks)
            expression = build_creation_session(CreationContext.capture(window.tracks,120,4),
                CreationBrief(CreationAction.EXPRESS,source_track_id=1,bars=1,
                              rewrite_velocity=True,shape_durations=True), "a")
            assert window._apply_creation_session(expression,frozenset({"expression"}))
            assert window.tracks[0] is source
            assert source.duration_scale == 1.5
            assert [n for n in project_track_notes(source) if n.start>=4000] == [
                n for n in project_track_notes(before[0]) if n.start>=4000]
            expressed = deepcopy(window.tracks)
            window._undo_project()
            assert window.tracks == before
            window._redo_project()
            assert window.tracks == expressed
            adaptation = build_creation_session(CreationContext.capture(window.tracks,120,4),
                CreationBrief(CreationAction.ADAPT,source_track_id=1,melody_instrument=11))
            assert window._apply_creation_session(adaptation,frozenset({"adaptation"}))
            adapted = deepcopy(window.tracks)
            assert [t.bdo_track_volume for t in adapted] == [30,30]
            assert adapted[0].bdo_track_settings == adapted[1].bdo_track_settings
            request = ExportRequest(direct_tracks=freeze_export_tracks(adapted),bpm=120,
                time_signature=4,out_path=Path("unused"),character_name="Test",owner_id=123,
                conversion=ConversionSettings.bdo_import_defaults(),pitch_plan=PitchTransformPlan(0),
                reverb=0,delay=0,chorus=None,game_dir=Path("unused-game"))
            document = decode_score(prepare_export(request).data)
            assert sum(len(t.notes) for g in document.groups for t in g.tracks) == 4
            assert document.groups[0].tracks[0].volume == 30
            window._undo_project()
            assert window.tracks == expressed
            window._redo_project()
            assert window.tracks == adapted
            window.close()
            app.processEvents()
        ''')

    def test_stale_preview_cannot_apply_and_cancelled_worker_does_not_write(self):
        self.run_ui('''
            import time
            from PySide6.QtWidgets import QApplication, QDialog
            from PySide6.QtTest import QTest
            from bdo_music_composer.ui.main_window import MidiToBdoWindow
            from bdo_music_composer.ui.dialogs.creation_assistant_dialog import CreationAssistantDialog
            app=QApplication([])
            window=MidiToBdoWindow()
            window.tracks=[]
            dialog=CreationAssistantDialog(window)
            dialog._generate()
            deadline=time.monotonic()+20
            while dialog.worker is not None and time.monotonic()<deadline: QTest.qWait(10)
            assert dialog.worker is None
            assert dialog.sessions, dialog.status_label.text()
            window.bpm += 1
            dialog._accept_proposal()
            assert not dialog.apply_button.isEnabled()
            assert not window.tracks
            dialog.reject()
            cancelled=CreationAssistantDialog(window)
            cancelled._generate()
            cancelled.reject()
            deadline=time.monotonic()+20
            while cancelled.worker is not None and time.monotonic()<deadline: QTest.qWait(10)
            assert cancelled.worker is None
            assert cancelled.result()==QDialog.Rejected
            assert not window.tracks
            window.close()
            app.processEvents()
        ''')

    def test_current_clip_defaults_and_audition_scope_use_the_existing_async_engine(self):
        self.run_ui('''
            from types import SimpleNamespace
            from copy import deepcopy
            from PySide6.QtWidgets import QApplication
            from bdo_midi import Note
            from bdo_music_composer.ui.main_window import MidiToBdoWindow
            from bdo_music_composer.ui.dialogs.creation_assistant_dialog import CreationAssistantDialog
            from bdo_music_composer.ui.creation_audition_qt import CreationAudition
            from bdo_music_composer.editor.editor_models import TrackState,ArrangementClipState
            app=QApplication([])
            window=MidiToBdoWindow()
            a=TrackState(1,[Note(60,80,0,1500,0)],0,False,"first",17)
            b=TrackState(2,[Note(64,80,0,1500,0),Note(70,80,40000,500,0)],0,False,"second",17,
                arrangement_clips=[ArrangementClipState("selected",0,42000,0,42000)])
            window.tracks=[a,b]
            window._refresh_tracks()
            window._select_track(b)
            window.timeline.set_selected_clip(b,"selected")
            assert window.timeline._selected_clip_id=="selected",window.timeline.selected_clip_keys
            dialog=CreationAssistantDialog(window)
            assert dialog.source_combo.currentData()==(2,"selected"),(dialog.source_combo.currentData(),dialog.initial_track_id,dialog.initial_clip_id)
            dialog.action_combo.setCurrentIndex(3)
            assert dialog.source_combo.currentData()==(2,"selected")
            dialog.action_combo.setCurrentIndex(2)
            assert dialog.source_combo.currentData()==(2,"")
            assert dialog._preview_time_range()==(0,40500),dialog._preview_time_range()
            dialog.reject()
            calls=[]
            class Audio:
                def available(self): return True
                def cancel_loading(self): calls.append("cancel")
                def clear_playback(self): calls.append("clear")
                def load_procedural_project_async(self,tracks,*args): calls.append(("generic",tracks,args))
                def load_project_async(self,tracks,*args): calls.append(("pack",tracks,args))
                def finish_loading(self,start): return {"ready":True}
                def play(self): calls.append("play")
                def get_status(self): return SimpleNamespace(position_ms=1000,duration_ms=1500)
            host=SimpleNamespace(realtime_audio=Audio(),audio_sources={"preview_mode":"generic"},
                reverb=0,delay=0,chorus=None,
                _claim_playback_focus=lambda editor:None,
                _stop_preview=lambda **kw:None,
                _project_tracks_for_preview=lambda tracks:tracks,
                _realtime_preview_blockers=lambda tracks:[])
            audition=CreationAudition(host)
            before=deepcopy(a)
            audition.play([a],500,1000)
            prepared=next(c for c in calls if isinstance(c,tuple) and c[0]=="generic")
            assert prepared[1][0].notes==[Note(60,80,500,500,0)],prepared
            assert a==before
            audition._poll()
            assert "play" in calls and "clear" in calls
            assert not audition.active
            host.audio_sources={"preview_mode":"pack"}
            audition.play([a],500,1000)
            assert any(isinstance(c,tuple) and c[0]=="pack" for c in calls)
            audition.stop()
            host._realtime_preview_blockers=lambda tracks:["missing pack"]
            count=len(calls)
            audition.play([a],500,1000)
            assert len(calls)==count
            window.close()
            app.processEvents()
        ''')


if __name__=="__main__": unittest.main()
