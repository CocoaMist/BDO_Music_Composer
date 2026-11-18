"""Localized labels and errors for model connection settings."""

SCORE_AGENT_SETTINGS_TRANSLATIONS = {
    "模型设置": ("Model settings", "モデル設定", "모델 설정"),
    "自定义接口": ("Custom API", "カスタム API", "사용자 지정 API"),
    "模型服务": ("Model provider", "モデルサービス", "모델 서비스"),
    "接口预设": ("API preset", "API プリセット", "API 프리셋"),
    "OpenAI 兼容接口": ("OpenAI-compatible API", "OpenAI 互換 API", "OpenAI 호환 API"),
    "本机接口可留空": ("Optional for local APIs", "ローカル API では省略可", "로컬 API는 생략 가능"),
    "搜索或输入模型 ID": ("Search or enter a model ID", "モデル ID を検索・入力", "모델 ID 검색 또는 입력"),
    "刷新模型列表": ("Refresh model list", "モデル一覧を更新", "모델 목록 새로고침"),
    "可粘贴 API 基础地址或完整的聊天、模型列表端点。": (
        "Paste the base URL, the full chat completions endpoint, or the full model list endpoint.",
        "ベース URL、チャット補完またはモデル一覧の完全なエンドポイントを貼り付けられます。",
        "기본 URL이나 전체 채팅 완성 또는 모델 목록 엔드포인트를 붙여 넣을 수 있습니다.",
    ),
    "连接后自动更新模型列表。": (
        "The model list refreshes automatically once connected.",
        "接続後、モデル一覧が自動更新されます。",
        "연결되면 모델 목록이 자동으로 갱신됩니다.",
    ),
    "自动读取模型列表，也可以手动输入模型 ID。": (
        "Models load automatically. You can also enter a model ID.",
        "モデル一覧を自動取得します。モデル ID の手入力もできます。",
        "모델을 자동으로 불러옵니다. 모델 ID를 직접 입력할 수도 있습니다.",
    ),
    "粘贴 OpenAI 兼容地址，或选择本机服务预设。": (
        "Paste an OpenAI-compatible URL or choose a local preset.",
        "OpenAI 互換の URL を貼り付けるか、ローカル用プリセットを選択してください。",
        "OpenAI 호환 URL을 붙여 넣거나 로컬 프리셋을 선택하세요.",
    ),
    "已读取 {count} 个模型。": (
        "Models loaded: {count}.", "{count} 件のモデルを取得しました。", "모델 {count}개를 불러왔습니다.",
    ),
    "模型列表为空。": ("The model list is empty.", "モデル一覧が空です。", "모델 목록이 비어 있습니다."),
    "服务未提供模型目录。": (
        "The provider has no model catalog.", "サービスがモデル一覧を提供していません。", "서비스에서 모델 목록을 제공하지 않습니다.",
    ),
    "无法读取服务返回的模型目录。": (
        "Could not read the model catalog.", "返されたモデル一覧を読み取れませんでした。", "서비스가 반환한 모델 목록을 읽을 수 없습니다.",
    ),
    "仍可手动输入模型 ID。": (
        "You can still enter a model ID.", "モデル ID を手入力することもできます。", "모델 ID를 직접 입력할 수 있습니다.",
    ),
    "关闭模型设置": ("Close model settings", "モデル設定を閉じる", "모델 설정 닫기"),
    "选择模型": ("Model", "モデルを選ぶ", "모델 선택"),
    "低强度推理": ("Low effort", "推論・低", "낮은 추론 강도"),
    "高强度推理": ("High effort", "推論・高", "높은 추론 강도"),
    "最高强度推理": ("Max effort", "推論・最大", "최대 추론 강도"),
    "输入 API 密钥": ("Enter API key", "API キーを入力", "API 키 입력"),
    "连接选项": ("Connection options", "接続オプション", "연결 옵션"),
    "记住连接": ("Remember connection", "接続を保存", "연결 기억"),
    "已配置密钥，留空沿用": ("Leave blank to keep current key", "空欄のまま既存のキーを使用", "비워 두면 기존 키 유지"),
    "不勾选时，本次连接仅在程序运行期间使用。": (
        "Leave unchecked to use this connection for this session.",
        "オフにすると、このセッション内でのみ接続を使います。",
        "해제하면 현재 세션에서만 이 연결을 사용합니다.",
    ),
    "模型服务暂不可用，请稍后再试。": (
        "The model service is temporarily unavailable. Try again later.",
        "モデルサービスは一時的に利用できません。しばらくしてからお試しください。",
        "모델 서비스를 일시적으로 사용할 수 없습니다. 나중에 다시 시도하세요.",
    ),
    "模型连接": ("Model connection", "モデル接続", "모델 연결"),
    "创作请求会发送到你设置的 OpenAI 兼容接口。": (
        "Creation requests go to the OpenAI-compatible API you configure.",
        "創作リクエストは、設定した OpenAI 互換 API に送信されます。",
        "창작 요청은 설정한 OpenAI 호환 API로 전송됩니다.",
    ),
    "API 地址": ("API URL", "API URL", "API URL"),
    "模型 ID": ("Model ID", "モデル ID", "모델 ID"),
    "API 密钥": ("API key", "API キー", "API 키"),
    "响应方式": ("Response mode", "応答モード", "응답 모드"),
    "快速模式": ("Fast mode", "高速モード", "빠른 모드"),
    "深思模式": ("Thinking mode", "思考モード", "사고 모드"),
    "深思模式使用 DeepSeek 官方的高强度推理，回答通常更慢。": (
        "Thinking mode uses DeepSeek's high reasoning effort and usually takes longer.",
        "思考モードは DeepSeek 公式の高精度推論を使うため、応答に時間がかかる場合があります。",
        "사고 모드는 DeepSeek 공식 고강도 추론을 사용하며 일반적으로 응답이 더 느립니다.",
    ),
    "测试连接": ("Test connection", "接続をテスト", "연결 테스트"),
    "正在检查模型目录…": ("Checking the model catalog…", "モデル一覧を確認中…", "모델 목록 확인 중…"),
    "连接可用，目录中包含当前模型。": (
        "Connected. The catalog lists this model.",
        "接続できました。モデル一覧にこのモデルがあります。",
        "연결되었습니다. 목록에 이 모델이 있습니다.",
    ),
    "请输入可用的 API 地址。": (
        "Enter a valid API URL.", "有効な API URL を入力してください。", "유효한 API URL을 입력하세요.",
    ),
    "服务已响应，但目录里没有该模型。请核对模型 ID。": (
        "The service responded and its catalog lacks this model. Check the model ID.",
        "サービスは応答しましたが、一覧にこのモデルはありません。モデル ID を確認してください。",
        "서비스가 응답했지만 목록에 이 모델이 없습니다. 모델 ID를 확인하세요.",
    ),
    "该地址没有返回模型目录。请核对 API 地址。": (
        "The service has no catalog at this URL. Check the API URL.",
        "この URL にはモデル一覧がありません。API URL を確認してください。",
        "이 URL에는 모델 목록이 없습니다. API URL을 확인하세요.",
    ),
    "模型目录响应无法识别。请确认 API 兼容性。": (
        "The model catalog response is unrecognized. Check API compatibility.",
        "モデル一覧の応答を認識できません。API の互換性を確認してください。",
        "모델 목록 응답을 인식할 수 없습니다. API 호환성을 확인하세요.",
    ),
    "服务返回了重定向。请直接填写最终 API 地址。": (
        "The service returned a redirect. Enter the final API URL directly.",
        "サービスがリダイレクトを返しました。最終的な API URL を直接入力してください。",
        "서비스가 리디렉션을 반환했습니다. 최종 API URL을 직접 입력하세요.",
    ),
    "连接测试超时，请检查网络或 API 地址。": (
        "The connection test timed out. Check the network or API URL.",
        "接続テストがタイムアウトしました。ネットワークまたは API URL を確認してください。",
        "연결 테스트 시간이 초과되었습니다. 네트워크 또는 API URL을 확인하세요.",
    ),
    "无法连接模型服务，请检查网络或 API 地址。": (
        "Could not reach the model service. Check the network or API URL.",
        "モデルサービスに接続できません。ネットワークまたは API URL を確認してください。",
        "모델 서비스에 연결할 수 없습니다. 네트워크 또는 API URL을 확인하세요.",
    ),
    "地址不变时，留空沿用当前密钥": (
        "Leave blank to keep the key for this URL",
        "同じ URL のキーを使う場合は空欄のままにしてください",
        "이 URL의 기존 키를 사용하려면 비워 두세요",
    ),
    "用当前 Windows 账户加密保存": (
        "Save encrypted for this Windows account",
        "現在の Windows アカウントで暗号化して保存",
        "현재 Windows 계정에 암호화하여 저장",
    ),
    "取消勾选后点击应用，将只在本次运行中使用连接，并清除已保存的连接。": (
        "Apply with this unchecked to use the connection until you close the app and clear the saved connection.",
        "チェックを外して適用すると、アプリを閉じるまで接続が有効になり、保存済みの接続は削除されます。",
        "선택을 해제한 상태에서 적용하면 앱을 닫을 때까지만 연결이 유지되며 저장된 연결은 삭제됩니다.",
    ),
    "清除连接": ("Clear connection", "接続を消去", "연결 지우기"),
    "请输入 HTTPS 地址，或使用本机环回 HTTP 地址。": (
        "Enter an HTTPS URL or an HTTP URL on this computer's loopback interface.",
        "HTTPS URL またはこの PC のループバック用 HTTP URL を入力してください。",
        "HTTPS URL 또는 이 컴퓨터의 루프백 HTTP URL을 입력하세요.",
    ),
    "请输入有效的模型 ID。": (
        "Enter a valid model ID.", "有効なモデル ID を入力してください。", "유효한 모델 ID를 입력하세요.",
    ),
    "请输入此接口的有效 API 密钥。本机环回接口可以留空。": (
        "Enter a valid API key for this provider. You can leave it blank for a loopback API.",
        "この API の有効なキーを入力してください。ループバック接続では省略できます。",
        "이 API의 유효한 키를 입력하세요. 루프백 API의 경우 비워 둘 수 있습니다.",
    ),
    "无法更新已保存的连接。请检查本地账户的数据目录。": (
        "Could not update the saved connection. Check your local account's data folder.",
        "保存済みの接続を更新できませんでした。ローカルアカウントのデータフォルダーを確認してください。",
        "저장된 연결을 업데이트할 수 없습니다. 로컬 계정의 데이터 폴더를 확인하세요.",
    ),
}
