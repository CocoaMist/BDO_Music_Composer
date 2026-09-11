"""Localized copy introduced by cross-surface UI refinements."""

from __future__ import annotations


UI_REFINEMENT_TRANSLATIONS = {
    "MIDI 中没有可导入的音符事件。": (
        "The MIDI contains no note events that can be imported.",
        "MIDIに読み込み可能なノートイベントがありません。",
        "MIDI에 가져올 수 있는 음표 이벤트가 없습니다.",
    ),
    "MIDI 已载入 · 已兼容修复 {count} 个越界数据值；原文件未修改": (
        "MIDI loaded · repaired {count} out-of-range data values for compatibility; the original file was not changed",
        "MIDIを読み込みました · 範囲外データ値{count}件を互換修復しました。元ファイルは変更していません",
        "MIDI 불러옴 · 범위를 벗어난 데이터 값 {count}개를 호환 복구했습니다. 원본 파일은 변경하지 않았습니다",
    ),
    " · 已兼容修复 {count} 个越界数据值（原文件未修改）": (
        " · repaired {count} out-of-range data values for compatibility (original file unchanged)",
        " · 範囲外データ値{count}件を互換修復（元ファイルは未変更）",
        " · 범위를 벗어난 데이터 값 {count}개 호환 복구(원본 파일 변경 없음)",
    ),
    "BDO 曲谱必须包含有效 Owner ID。可以立即从游戏曲谱读取，也可以打开设置手动处理。": (
        "A BDO score requires a valid Owner ID. Read it from a game score now, or open Settings to handle it manually.",
        "BDO楽譜には有効なOwner IDが必要です。ゲーム内楽譜から今すぐ読み取るか、設定を開いて手動で指定できます。",
        "BDO 악보에는 유효한 Owner ID가 필요합니다. 게임 악보에서 바로 읽거나 설정을 열어 직접 처리할 수 있습니다.",
    ),
    "{status}\n当前来源：{source}": (
        "{status}\nCurrent source: {source}",
        "{status}\n現在の取得元：{source}",
        "{status}\n현재 소스: {source}",
    ),
    "下载中": ("Downloading", "ダウンロード中", "다운로드 중"),
    "也可以从“项目”菜单导入 MIDI": (
        "You can also import MIDI from the Project menu",
        "「プロジェクト」メニューからMIDIを読み込むこともできます",
        "'프로젝트' 메뉴에서 MIDI를 가져올 수도 있습니다",
    ),
    "去设置": ("Open Settings", "設定を開く", "설정 열기"),
    "双击轨道，打开音符编辑器写下第一个音符": (
        "Double-click a track to open the note editor and write the first note",
        "トラックをダブルクリックしてノートエディターを開き、最初のノートを入力",
        "트랙을 두 번 클릭해 노트 편집기를 열고 첫 음표를 입력하세요",
    ),
    "可更新": ("Update available", "更新あり", "업데이트 가능"),
    "完整路径；文本过长时可横向滚动查看": (
        "Full path; scroll horizontally when the text is too long",
        "完全なパスです。長い場合は横スクロールで確認できます",
        "전체 경로입니다. 텍스트가 길면 가로로 스크롤해 확인하세요",
    ),
    "已准备": ("Update ready", "更新準備完了", "업데이트 준비됨"),
    "常用八度移调": (
        "Common octave transposition",
        "よく使うオクターブ移調",
        "자주 쓰는 옥타브 조옮김",
    ),
    "当前有 {count} 项必须先处理的问题。选择“打开”可定位到第一个相关轨道或音符。": (
        "There are {count} blocking issues. Choose Open to locate the first related track or note.",
        "先に処理が必要な問題が{count}件あります。「開く」で最初の関連トラックまたはノートへ移動します。",
        "먼저 처리해야 할 문제가 {count}개 있습니다. '열기'를 선택하면 첫 관련 트랙이나 음표로 이동합니다.",
    ),
    "恢复为不移调": (
        "Reset to no transposition",
        "移調なしに戻す",
        "조옮김 없음으로 복원",
    ),
    "所选片段": ("Selected clip", "選択したクリップ", "선택한 클립"),
    "无法导出：存在阻断项": (
        "Cannot export: blocking issues",
        "書き出しできません：未解決の問題があります",
        "내보낼 수 없음: 차단 문제가 있습니다",
    ),
    "无法导出：缺少 Owner ID": (
        "Cannot export: Owner ID missing",
        "書き出しできません：Owner IDがありません",
        "내보낼 수 없음: Owner ID 누락",
    ),
    "更新包已验证，将在下次启动时自动安装。": (
        "The verified update will install automatically on the next launch.",
        "更新パッケージを検証しました。次回起動時に自動でインストールします。",
        "업데이트 패키지가 검증되었으며 다음 실행 시 자동으로 설치됩니다.",
    ),
    "正在后台获取经过签名验证的更新包。": (
        "Downloading the signed update package in the background.",
        "署名検証対象の更新パッケージをバックグラウンドで取得しています。",
        "서명 검증된 업데이트 패키지를 백그라운드에서 받고 있습니다.",
    ),
    "状态：已关闭自动检查；可随时手动检查更新。": (
        "Status: automatic checks are off; you can check manually at any time.",
        "状態：自動確認はオフです。いつでも手動で確認できます。",
        "상태: 자동 확인이 꺼져 있습니다. 언제든 수동으로 확인할 수 있습니다.",
    ),
    "状态：已启用自动检查和后台下载；安装会在下次启动完成。": (
        "Status: automatic checks and background downloads are on; installation completes on the next launch.",
        "状態：自動確認とバックグラウンドダウンロードはオンです。次回起動時にインストールします。",
        "상태: 자동 확인과 백그라운드 다운로드가 켜져 있습니다. 다음 실행 시 설치됩니다.",
    ),
    "状态：已启用自动检查；发现新版本后等待手动下载。": (
        "Status: automatic checks are on; new versions wait for manual download.",
        "状態：自動確認はオンです。新しいバージョンは手動ダウンロードを待ちます。",
        "상태: 자동 확인이 켜져 있습니다. 새 버전은 수동 다운로드를 기다립니다.",
    ),
    "稍后处理": ("Later", "後で", "나중에"),
    "重置": ("Reset", "リセット", "재설정"),
    "搜索快捷键或操作": (
        "Search shortcuts or actions",
        "ショートカットまたは操作を検索",
        "단축키 또는 작업 검색",
    ),
    "搜索致谢与许可证": (
        "Search acknowledgements and licenses",
        "謝辞とライセンスを検索",
        "감사의 말 및 라이선스 검색",
    ),
    "查找下一个": ("Find next", "次を検索", "다음 찾기"),
}


__all__ = ["UI_REFINEMENT_TRANSLATIONS"]
