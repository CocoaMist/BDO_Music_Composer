"""Localized copy introduced by cross-surface UI refinements."""

from __future__ import annotations


UI_REFINEMENT_TRANSLATIONS = {
    "共 {count} 项": ("Total · {count}", "全 {count} 件", "총 {count}개"),
    "下载": ("Downloads", "ダウンロード", "다운로드"),
    "暂无下载": ("No downloads yet", "ダウンロードはまだありません", "다운로드가 없습니다"),
    "搜索下载": ("Search downloads", "ダウンロードを検索", "다운로드 검색"),
    "下载完成": ("Completed", "ダウンロード完了", "다운로드 완료"),
    "下载失败": ("Download failed", "ダウンロードに失敗しました", "다운로드 실패"),
    "下载完成 · {name}": (
        "Download complete · {name}", "ダウンロード完了 · {name}", "다운로드 완료 · {name}",
    ),
    "下载失败 · {name}": (
        "Download failed · {name}", "ダウンロード失敗 · {name}", "다운로드 실패 · {name}",
    ),
    "取消下载": ("Cancel download", "ダウンロードをキャンセル", "다운로드 취소"),
    "重新下载": ("Retry download", "ダウンロードを再試行", "다운로드 다시 시도"),
    "打开下载文件夹": ("Open downloads folder", "ダウンロードフォルダーを開く", "다운로드 폴더 열기"),
    "打开曲谱": ("Open score", "楽譜を開く", "악보 열기"),
    "无法打开下载文件夹": (
        "Could not open the downloads folder",
        "ダウンロードフォルダーを開けませんでした",
        "다운로드 폴더를 열 수 없습니다",
    ),
    "下载中 · {received}": (
        "Downloading · {received}", "ダウンロード中 · {received}", "다운로드 중 · {received}",
    ),
    "下载中 · {received} / {total} · {percent}%": (
        "Downloading · {received} / {total} · {percent}%",
        "ダウンロード中 · {received} / {total} · {percent}%",
        "다운로드 중 · {received} / {total} · {percent}%",
    ),
    "在线曲谱库": ("Online Score Library", "オンライン楽譜ライブラリ", "온라인 악보 라이브러리"),
    "音乐库": ("Music Library", "音楽ライブラリ", "음악 라이브러리"),
    "进入音乐库": ("Enter Music Library", "音楽ライブラリを開く", "음악 라이브러리 열기"),
    "您即将进入由 CN服务器 温尘梦 玩家收集数据制作搭建的公益网站": (
        "You're about to enter a public-interest website created by 温尘梦, a CN-server player who collected the data.",
        "CNサーバーのプレイヤー「温尘梦」がデータを収集して制作した公益サイトを開きます。",
        "CN 서버 플레이어 ‘温尘梦’ 님이 데이터를 모아 만든 공익 웹사이트로 이동합니다.",
    ),
    "在浏览器中打开 BDO 曲谱库": (
        "Open the BDO Score Library in your browser",
        "ブラウザーでBDO楽譜ライブラリを開く",
        "브라우저에서 BDO 악보 라이브러리 열기",
    ),
    "用默认浏览器打开": ("Open in Default Browser", "既定のブラウザーで開く", "기본 브라우저에서 열기"),
    "无法启动默认浏览器。": (
        "The default browser could not start.",
        "既定のブラウザーを起動できませんでした。",
        "기본 브라우저를 시작할 수 없습니다.",
    ),
    "网页后退": ("Previous page", "前のページ", "이전 페이지"),
    "网页前进": ("Next page", "次のページ", "다음 페이지"),
    "重新加载曲谱库": ("Reload score library", "楽譜ライブラリを再読み込み", "악보 라이브러리 새로 고침"),
    "正在加载曲谱库…": ("Loading the score library…", "楽譜ライブラリを読み込み中…", "악보 라이브러리 불러오는 중…"),
    "无法加载曲谱库。": (
        "The score library could not load.",
        "楽譜ライブラリを読み込めませんでした。",
        "악보 라이브러리를 불러올 수 없습니다.",
    ),
    "可在默认浏览器中确认网站能否访问。": (
        "Check whether the site opens in your default browser.",
        "既定のブラウザーでサイトにアクセスできるか確認できます。",
        "기본 브라우저에서 웹사이트에 접속할 수 있는지 확인할 수 있습니다.",
    ),
    "等待内嵌浏览器响应超时。": (
        "The embedded browser did not respond in time.",
        "内蔵ブラウザーの応答がタイムアウトしました。",
        "내장 브라우저가 시간 내에 응답하지 않았습니다.",
    ),
    "证书校验失败。": (
        "Certificate verification failed.",
        "証明書の検証に失敗しました。",
        "인증서 확인에 실패했습니다.",
    ),
    "无法解析曲谱库域名。": (
        "The score library’s domain name could not be resolved.",
        "楽譜ライブラリのドメイン名を解決できませんでした。",
        "악보 라이브러리의 도메인 이름을 확인할 수 없습니다.",
    ),
    "连接曲谱库超时。": (
        "The connection to the score library timed out.",
        "楽譜ライブラリへの接続がタイムアウトしました。",
        "악보 라이브러리 연결 시간이 초과되었습니다.",
    ),
    "无法建立或维持与曲谱库的连接。": (
        "The connection to the score library could not be established or was interrupted.",
        "楽譜ライブラリに接続できなかったか、接続が中断されました。",
        "악보 라이브러리에 연결할 수 없거나 연결이 끊겼습니다.",
    ),
    "曲谱库服务器返回了无效响应。": (
        "The score library returned an invalid response.",
        "楽譜ライブラリのサーバーから無効な応答が返されました。",
        "악보 라이브러리 서버가 잘못된 응답을 반환했습니다.",
    ),
    "曲谱库网页跳转失败。": (
        "The score library could not redirect to the next page.",
        "楽譜ライブラリでページを移動できませんでした。",
        "악보 라이브러리 페이지를 리디렉션할 수 없습니다.",
    ),
    "当前安装缺少内置浏览器组件。": (
        "This installation is missing the embedded browser.",
        "このインストールには内蔵ブラウザーがありません。",
        "현재 설치에 내장 브라우저가 없습니다.",
    ),
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


TIMELINE_HELP_TRANSLATIONS = {
    "轨道操作": ("Track controls", "トラック操作", "트랙 조작"),
    "导航与视图": ("Navigation and view", "移動と表示", "탐색 및 보기"),
    "复制片段": ("Copy clip", "クリップをコピー", "클립 복사"),
    "粘贴到播放头": ("Paste at playhead", "再生ヘッドへ貼り付け", "재생 헤드에 붙여넣기"),
    "向后复制": ("Duplicate forward", "後方へ複製", "뒤로 복제"),
    "收紧右边界": ("Tighten right edge", "右端を詰める", "오른쪽 경계 줄이기"),
    "选择轨道": ("Select track", "トラックを選択", "트랙 선택"),
    "跳到首尾轨道": ("Go to first or last track", "先頭・末尾のトラックへ移動", "첫 번째 또는 마지막 트랙으로 이동"),
    "轨道静音": ("Mute track", "トラックをミュート", "트랙 음소거"),
    "轨道独奏": ("Solo track", "トラックをソロ", "트랙 솔로"),
    "轨道静音（M）": ("Track mute (M)", "トラックのミュート (M)", "트랙 음소거(M)"),
    "轨道独奏（S）": ("Track solo (S)", "トラックのソロ (S)", "트랙 솔로(S)"),
    "调整音量": ("Adjust volume", "音量を調整", "볼륨 조절"),
    "折叠/展开当前组": ("Fold or unfold current group", "現在のグループを折りたたむ・展開する", "현재 그룹 접기 또는 펼치기"),
    "移动播放头或音块": ("Move playhead or clip", "再生ヘッドまたはクリップを移動", "재생 헤드 또는 클립 이동"),
    "上/下一个音块或标记边界": ("Previous or next clip edge or marker", "前後のクリップ端またはマーカーへ移動", "이전 또는 다음 클립 경계나 마커로 이동"),
    "扩展范围/粗调": ("Extend range or use coarse steps", "範囲を拡張・粗く調整", "범위 확장 또는 큰 단위 조절"),
    "缩放到范围/音块": ("Zoom to range or clip", "範囲またはクリップにズーム", "범위 또는 클립에 맞추기"),
    "恢复视图": ("Restore view", "表示を戻す", "보기 복원"),
    "适配整首宽度": ("Fit full song to width", "曲全体が収まるように表示", "곡 전체를 너비에 맞추기"),
    "适配轨道高度": ("Fit track heights", "トラックの高さを合わせる", "트랙 높이 맞추기"),
    "Ctrl+滚轮": ("Ctrl+Wheel", "Ctrl+ホイール", "Ctrl+휠"),
    "Shift+滚轮": ("Shift+Wheel", "Shift+ホイール", "Shift+휠"),
    "缩放": ("Zoom", "ズーム", "확대·축소"),
    "横向滚动": ("Horizontal scroll", "横スクロール", "가로 스크롤"),
    "临时取消吸附": ("Temporarily bypass snap", "一時的にスナップを解除", "일시적으로 스냅 해제"),
    "清除选择（也可单击空白处）": ("Clear selection (or click empty space)", "選択解除（空白をクリックしても可）", "선택 해제(빈 곳 클릭 가능)"),
}


__all__ = ["TIMELINE_HELP_TRANSLATIONS", "UI_REFINEMENT_TRANSLATIONS"]
