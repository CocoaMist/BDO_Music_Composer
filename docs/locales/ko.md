# BDO Music Composer

[简体中文](zh-CN.md) · [English](en.md) · [日本語](ja.md) · [한국어](ko.md) · [프로젝트 홈](../../README.md)

BDO Music Composer는 Black Desert 작곡가를 위한 로컬 멀티트랙 편집기입니다. MIDI 가져오기, Clip 배치, 음표와 벨로시티 편집, 게임용 악보 내보내기를 한 흐름으로 연결합니다. 범용 DAW가 아니며 Pearl Abyss와 제휴하지 않습니다.

> 이 도구는 제한된 콘텐츠를 취득하거나 배포하지 않습니다. 외부 콘텐츠의 출처와 이용 권한은 사용자가 확인해야 합니다.

<!-- section:status -->
## 지금 사용해도 되나요

2026.11.0.1은 멀티트랙 편집, 자동 저장, 로컬 미리듣기, 참고 오디오 채보 지원, BDO v9 악보 내보내기를 제공합니다. Windows 실행 파일의 시작 및 오디오 채보 자체 테스트를 통과했습니다. 전체 회귀 테스트에는 알려진 실패가 남아 있습니다. 자세한 내용은 [릴리스 노트](https://github.com/CocoaMist/BDO_Music_Composer/releases/tag/v2026.11.0.1)를 참고하세요.

<!-- section:features -->
## 주요 기능

- MIDI를 가져오거나 빈 프로젝트에서 시작해 멀티트랙 타임라인의 클립을 배치, 분할, 이동, 병합합니다.
- 마커, 클립, 그리드 순서의 자동 스냅을 사용하고 피아노 롤에서 음표, 벨로시티, 리듬, 주법을 편집합니다.
- 현재 편집 상태를 유지하면서 기존 악보를 열고 다시 내보냅니다.
- 로컬 채보 지원 결과를 확정 전에 편집 가능한 초안으로 검토합니다.
- 취소 가능한 최적화, 자동 저장, 자동 내보내기 검증, 로컬 프로젝트 관리를 제공합니다.

**창작 도우미**는 짧은 곡의 초안, 멜로디에 어울리는 반주, 게임 악기에 맞춘 편곡, 셈여림과 음 길이 조정을 제안합니다. 미리 들은 뒤 적용할 성부를 고를 수 있으며 변경 사항을 되돌릴 수 있습니다. 모델 설정에서 DeepSeek와 호환 API를 연결할 수 있습니다. [구현 및 모델 계획](../CREATION_ASSISTANT_PLAN.md)(중국어)도 참고하세요.

<!-- section:requirements -->
## 설치와 실행

[릴리스 페이지](https://github.com/CocoaMist/BDO_Music_Composer/releases)에서 Windows x64 ZIP을 내려받아 압축을 풀고 `BDO-Music-Composer.exe`를 실행하세요. 중국어 설명서는 PDF로도 따로 받을 수 있습니다. 소스에서 실행하려면 [기여 안내](../../CONTRIBUTING.md)에 따라 Python 3.12 환경을 준비한 뒤 `main.py`를 실행하세요.

<!-- section:workflow -->
## 기본 작업 흐름

1. 프로젝트를 만들거나 MIDI를 가져오거나 악보를 엽니다.
2. 타임라인에서 클립을 배치하고 피아노 롤에서 음표를 다듬습니다.
3. 미리듣기와 자동 검증으로 결과를 확인합니다.
4. 유효한 Owner ID로 내보낸 뒤 게임 안에서 확인합니다.

<!-- section:local-assets -->
## 로컬 콘텐츠

프로젝트, 설정, 캐시와 외부 콘텐츠는 로컬에 남습니다. 외부 콘텐츠가 저장소나 배포 파일에 자동으로 들어가지 않으며 선택 콘텐츠가 없어도 주요 편집과 내보내기를 사용할 수 있습니다.

릴리스 페이지에서는 근사 미리듣기용
`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`를 별도 파일로
제공할 수 있습니다. 앱에는 내장되지 않습니다. 설정의 **음원 팩**에서 이 파일이나
필요한 권리를 보유한 다른 호환 팩을 선택할 수 있으며 내장 범용 음원은 항상 사용할 수 있습니다.

v4 WAV 바이트는 독립적인 CC0 라이브러리인
[VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE),
[Versilian Community Sample Library](https://github.com/sgossner/VCSL),
[FreePats CC0 악기 뱅크](https://freepats.zenvoid.org/)에서 선택되었습니다.
`manifest.json`은 모든 슬롯의 출처, 업스트림 상대 경로와 SHA-256을 기록합니다.
Black Desert 클라이언트 오디오는 포함하지 않으며 게임 원음이나 A/B 검증 음원이 아닙니다.
v1.2.1 SHA-256은
`82cea29f1316b943571663e4150b31e353da4ab9f556141ed65b6598a384db63`입니다.

<!-- section:architecture -->
## 프로젝트 구조

앱, 핵심 기능, 문서, 테스트, 스크립트와 패키징을 분리합니다. [아키텍처](../ARCHITECTURE.md)와 [확장 로드맵](../OPTIMIZATION_EXTENSION_ROADMAP.md)을 참고하세요.

<!-- section:invariants -->
## 정확성 경계

현재 편집 상태는 미리듣기, 저장, 내보내기까지 유지되어야 합니다. 원본 가져오기로 조용히 되돌아가거나 지원하지 않는 출력을 성공으로 표시하지 않습니다. [AGENTS.md](../../AGENTS.md)를 참고하세요.

<!-- section:testing -->
## 검증

유지관리자는 전체 테스트, 저장소 구조 검사, 관련 UI 및 패키징 스모크 테스트를 실행합니다. 최소 조건은 [AI 컨텍스트](../AI_CONTEXT.md)와 [인수인계 안내](../AGENT_HANDOFF.md)에 있습니다.

<!-- section:packaging -->
## 배포

공개 빌드는 의존성, 라이선스, 개인정보, 리소스와 시작 검사를 통과해야 합니다. 사용자 프로젝트, 신원 정보, 캐시, 외부 콘텐츠와 개인 키는 배포 파일에 포함하지 않습니다.

<!-- section:privacy -->
## 개인정보

계정 로그인, 텔레메트리, 파일 업로드가 없습니다. 악보에는 Owner ID와 캐릭터 정보가 포함될 수 있으므로 공개 저장소에 커밋하지 마세요.

<!-- section:docs -->
## 문서

[문서 색인](../README.md)에서 시작하세요. 개발자는 [아키텍처](../ARCHITECTURE.md), [AI 컨텍스트](../AI_CONTEXT.md), [인수인계 안내](../AGENT_HANDOFF.md)도 읽어야 합니다.

<!-- section:license -->
## 라이선스와 감사

원본 코드는 [MIT License](../../LICENSE)를 따릅니다. 제3자 구성 요소와 참고 자료에는 각각의 조건이 적용됩니다. [제3자 고지](../../THIRD_PARTY_NOTICES.md)를 참고하세요.
