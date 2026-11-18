"""Bundled, read-only music theory notes for the score agent."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


MAX_THEORY_QUERY_LENGTH = 240
MAX_THEORY_MATCHES = 5
_WORDS = re.compile(r"v7?\s*/\s*(?:vii?|iv|iii?|v)(?![a-z0-9])|[a-z0-9]+|[\u3400-\u9fff]+")
_MUSIC_SYMBOLS = str.maketrans({"♭": "b", "⁄": "/", "∕": "/"})
_NOTATION = frozenset({"6 8", "biii", "bvi", "bvii"})
_GAME_TERMS = frozenset({"bdo", "black desert", "黑沙", "黑色沙漠", "游戏曲谱"})


@dataclass(frozen=True, slots=True)
class _Source:
    title: str
    url: str = ""
    path: str = ""


_SOURCES = {
    "omt-harmony": _Source(
        "Open Music Theory · Introduction to Harmony",
        url="https://viva.pressbooks.pub/openmusictheorycopy/chapter/intro-to-harmony/",
    ),
    "omt-tonicization": _Source(
        "Open Music Theory · Tonicization",
        url="https://viva.pressbooks.pub/openmusictheory/chapter/tonicization/",
    ),
    "omt-inversion": _Source(
        "Open Music Theory · Inversion",
        url="https://viva.pressbooks.pub/openmusictheory/chapter/inversion/",
    ),
    "omt-satb": _Source(
        "Open Music Theory · Chords in SATB style",
        url="https://viva.pressbooks.pub/openmusictheory/chapter/chords-in-satb-style/",
    ),
    "omt-modal-mixture": _Source(
        "Open Music Theory · Modal Mixture",
        url="https://viva.pressbooks.pub/openmusictheory/chapter/modal-mixture/",
    ),
    "omt-transposition": _Source(
        "Open Music Theory · Pitch-Class Sets, Normal Order, and Transformations",
        url="https://viva.pressbooks.pub/openmusictheory/chapter/pc-sets-normal-order-and-transformations/",
    ),
    "puget-nonchord": _Source(
        "Music Theory for the 21st-Century Classroom · Non-Chord Tones",
        url="https://musictheory.pugetsound.edu/mt21c/NonChordTonesIntroduction.html",
    ),
    "puget-minor": _Source(
        "Music Theory for the 21st-Century Classroom · Minor Scales",
        url="https://musictheory.pugetsound.edu/mt21c/MinorScales.html",
    ),
    "puget-cadences": _Source(
        "Music Theory for the 21st-Century Classroom · Cadences",
        url="https://musictheory.pugetsound.edu/mt21c/cadences.html",
    ),
    "macalester-harmonization": _Source(
        "Multimodal Musicianship · Melody harmonization",
        url="https://pressbooks.macalester.digital/multimodalmusicianship/chapter/melody-harmonization/",
    ),
    "belkin-orchestration": _Source(
        "Alan Belkin · Orchestration Theory, Register and Planes of Tone",
        url="https://alanbelkinmusic.com/PDF/BelkinOrchestrationTheory.pdf",
    ),
    "umn-orchestration": _Source(
        "University of Minnesota · Techniques of Orchestration",
        url="https://open.lib.umn.edu/musiccomposition/chapter/type-i-orchestration/",
    ),
    "bdo-theory": _Source("BDO Composer · 乐理、配器与拟真奏法", path="docs/MUSIC_THEORY_KNOWLEDGE_BASE.md"),
    "bdo-authoring": _Source("BDO Composer · 作曲器界面契约", path="docs/BDO_COMPOSITION_AUTHORING.md"),
    "bdo-articulation": _Source("BDO Composer · 乐器奏法参考", path="docs/INSTRUMENT_ARTICULATION_GUIDE.md"),
    "bdo-drum-map": _Source("BDO Composer · GM 鼓键导入映射", path="src/bdo_midi/instruments.py"),
    "bdo-audio-alignment": _Source("BDO Composer · 参考音频证据", path="docs/CREATION_ASSISTANT_PLAN.md"),
}


@dataclass(frozen=True, slots=True)
class _Article:
    id: str
    title: str
    keywords: str
    summary: str
    practice: str
    source: str


_ARTICLES = (
    _Article(
        "pitch-and-scales", "音程、音级与音阶",
        "音程|音级|音阶|半音|全音|大小调|调式|八度|interval|scale degree|scale|semitone|whole step|mode|octave",
        "半音差描述实际音高距离，音程名称还取决于音名。大调音阶按全全半全全全半排列，关系大小调可共享音集合。",
        "核对终止、重音和低音中心，再解释音阶或调式。钢琴卷帘中的 MIDI 音高不能单独确定等音拼写。",
        "omt-harmony",
    ),
    _Article(
        "tonal-center", "调性中心与转调",
        "调性|转调|主音|调性中心|关系小调|关系大调|关系大小调|离调|自然小调|和声小调|升七级|音级集合|c 大调|a 小调|"
        "key signature|tonal center|tonic|modulation|relative minor|relative major|natural minor|harmonic minor|pitch collection",
        "相同音集合可支持不同调性。C 大调与 A 自然小调都包含 G，A 小调可在属到主等语境下用 G♯ 作导音。"
        "临时出现升降音也可能来自借用或局部主音化。",
        "仅凭 C、E、G、A 可提出 C 大调和 A 小调作为候选。检查重拍、长音、句尾落点与低音，"
        "再判断哪个中心更稳。确认转调还要有新中心延续或收束的证据。",
        "puget-minor",
    ),
    _Article(
        "chord-construction", "和弦构成与转位",
        "和弦|三和弦|七和弦|和弦转位|根音|大三|小三|属七|斜杠和弦|chord|triad|seventh chord|inversion|root position|chord tone|slash chord",
        "大三和弦由根音、大三度和纯五度构成，小三和弦将三度降低半音。转位由最低音决定，根音和最低音可以不同。",
        "G/B 表示 G 大三和弦的最低音为 B，可在 C 大调里用 C–G/B–Am 形成 C–B–A 的低音线。分解和弦跨多个起音时，结合节拍和低音判断。",
        "omt-inversion",
    ),
    _Article(
        "functional-harmony", "和声功能与和弦进行",
        "和声|和弦进行|功能和声|和声功能|属功能|下属|级数|罗马数字|harmony|chord progression|harmonic function|dominant|predominant|roman numeral",
        "常见调性进行中，主功能提供稳定，下属或前属功能引向属功能，属功能常回到主和弦。调式与循环型伴奏可能遵循不同逻辑。",
        "给出级数前先说明假定调性。用低音和落点验证功能，识别重复循环与真正的乐句收束。",
        "omt-harmony",
    ),
    _Article(
        "secondary-dominants", "副属和弦与临时主音化",
        "副属和弦|副属|副属七和弦|临时主音化|应用和弦|重属和弦|secondary dominant|applied chord|tonicization|"
        "v/ii|v/iii|v/iv|v/v|v/vi|v7/ii|v7/iii|v7/iv|v7/v|v7/vi",
        "副属和弦暂时把调内目标和弦当作主和弦来强调。斜线后的罗马数字是目标，V/V 是属和弦的属和弦。",
        "在 C 大调试奏 D7–G–C。D7 的 F♯ 向 G 解决，D7 是 V7/V。根据后续进行再判断是否转调。",
        "omt-tonicization",
    ),
    _Article(
        "modal-mixture", "同主音大小调与借用和弦",
        "调式混合|调式借用|借和弦|借用和弦|同主音|modal mixture|mode mixture|modal interchange|"
        "borrowed chord|parallel minor|biii|bvi|bvii",
        "调式借用可从同主音的另一个调式取得和弦，例如从 C 小调向 C 大调借用 F 小三和弦 iv。借用和弦可改变色彩，同时维持原来的调性中心。",
        "把 C–F–G–C 的 F 换成 Fm，试听 A 变 A♭ 的效果。核对后续低音和终止，再判断是否出现新的调性中心。",
        "omt-modal-mixture",
    ),
    _Article(
        "cadence-and-phrase", "乐句、收束与终止式",
        "乐句|终止|半终止|正格终止|阻碍终止|假终止|欺骗终止|结束感|收束|换气|cadence|phrase ending|phrasing|"
        "authentic cadence|half cadence|deceptive cadence|breath",
        "按乐句末端判断终止。属到主可形成正格终止，停在属可形成半终止。属和弦建立回主期待后改落其他和弦可形成阻碍终止，常见为大调 V–vi。",
        "在 C 大调比较句尾 G–C 和 G–Am。用旋律停顿、长音和低音落点判断是否收束，"
        "乐句内部或连续循环里的同样和弦对通常先描述为进行。",
        "puget-cadences",
    ),
    _Article(
        "nonchord-tones", "和弦外音、经过音与挂留",
        "和弦外音|非和弦音|经过音|邻音|倚音|挂留|non chord tone|nonchord tone|passing tone|neighbor tone|suspension",
        "同方向级进连接两个和弦音常是经过音，级进离开再返回常是邻音。挂留常由保持前一和弦音、形成不协和再级进解决组成。",
        "连着看同一声部的前中后三音、重拍与伴奏和弦。避免仅按一个垂直切片清理非和弦音。",
        "puget-nonchord",
    ),
    _Article(
        "chord-voicing", "和弦排列、共同音与声部连接",
        "和弦排列|开放排列|密集排列|紧密排列|闭合排列|声部间距|声部交叉|声部配置|共同音|声部进行|反向进行|"
        "voicing|open voicing|closed voicing|close voicing|open position|chord spacing|voice leading|voice crossing|common tone",
        "和弦排列改变各音所处的八度与间距。音级集合和最低音保持相同时，重新排列上声部仍可维持原和弦与转位。",
        "比较 C3–E3–G3 与 C3–G3–E4，试听时把音量和音源设成相同。连接到下一和弦时，先找可留在原声部的共同音，再考虑移动其他声部。",
        "omt-satb",
    ),
    _Article(
        "meter-and-groove", "拍号、切分与节奏重心",
        "拍号|节拍|切分|反拍|弱起|附点|三连音|节奏重心|复拍子|6 8|meter|time signature|syncopation|offbeat|pickup|compound meter|groove|triplet",
        "4/4 常以第一拍为主要重心，第三拍为次重心。6/8 常分为两个附点四分音符的拍组。切分通过弱位重音或延音模糊预期重心。",
        "看重音和重复拍组判断律动。对黑沙 6/8 项目以当前导出校验为准，界面标签不足以证明 v9 文件对分母的支持。",
        "bdo-authoring",
    ),
    _Article(
        "dynamics-and-timing", "力度层次、量化与拟真",
        "力度|midi 力度|听感响度|听感一定会响|力度和音量|力度从|轨道音量|强弱|渐强|渐弱|重音|量化|拟真|自然化|微时序|"
        "velocity|velocity versus volume|perceived loudness|track gain|dynamics|crescendo|accent|quantization|humanization|timing",
        "80→90 相当于 MIDI 力度数值增加 12.5%。音源对起音、音色及响度的响应取决于乐器和音区，轨道音量又是另一层控制。",
        "固定音源、音高、时值、轨道音量与效果，对照试听不同力度。先保护手工力度、切分和同步起音，再决定是否调整。",
        "bdo-theory",
    ),
    _Article(
        "melody-first-harmonization", "从旋律配和弦与和声节奏",
        "给旋律配和弦|旋律配和弦|旋律配和声|只有旋律|没有低音|第一个和弦|每个旋律音|每个音换和弦|和声节奏|换和弦|"
        "harmonize melody|harmonize a melody|melody harmonization|harmonic rhythm|change chord for every melody note",
        "先看重拍、长音、反复音与句尾，再试候选和弦和换和弦频率。一个和弦可以托住多个旋律音，短音也可能是经过音或邻音。",
        "在假定 C 大调下，C–D–E–G 可先试 C 和弦，让 D 经过 C 到 E；以 A 为稳定落点的句子可另试 Am，"
        "短 G 是否为和弦外音要看节拍与后续。只给音名时先给候选，等看到音序再判断哪些音是经过音或邻音。",
        "macalester-harmonization",
    ),
    _Article(
        "texture-and-arranging", "织体、主旋律与伴奏",
        "织体|主旋律|副旋律|对位|伴奏盖住主旋律|伴奏盖住旋律|伴奏抢旋律|主旋律音符很密|旋律不突出|旋律留白|伴奏|"
        "贝斯|低音|分解和弦|配伴奏|八度加倍|同度加倍|texture|melody|counterpoint|accompaniment|bass line|arpeggio|"
        "accompaniment masks melody|octave doubling|unison doubling|foreground melody",
        "分清主旋律、低音支点和内声部，按音区、音色、起音密度与力度留空间。加倍可突出局部，但同区、同节奏层过密也会抢前景。",
        "保持旋律不动。可让第一小节的低音在和声换点进入，避开密集旋律起音；第二小节在旋律长音后半或停顿补稀疏和声。"
        "留白位置由实际乐句决定，试听完整与减配版，必要时只在句尾加倍。",
        "umn-orchestration",
    ),
    _Article(
        "low-register-clarity", "低音发糊、重复低音与声部间距",
        "低音区发糊|低音区混浊|低音发糊|低音发浑|低音堆三度|低频打架|低频混浊|重复低音|低音三度|低音区间距|"
        "muddy bass|muddy low register|low register voicing|low interval limit|bass doubling|low spacing",
        "低声部较宽的间距通常更清楚。同音加倍、低音区密集三度和长时间重叠都值得分开试听，具体效果取决于音色与音区。",
        "左手 C2–E2–G2 和贝斯 C2 重合时，可留贝斯 C2，去掉左手重复的 C2，把 E2/G2 提到 E3/G3。"
        "用相同音源、近似响度对照试听，核对和弦音与低音功能。",
        "belkin-orchestration",
    ),
    _Article(
        "orchestration-and-register", "配器、音域与移调",
        "配器|音域|音区|音色|混浊|移调|乐器适配|跨八度|超音域|orchestration|register|timbre|range|transposition|playable range",
        "不同音区会改变乐器音色和可演奏性。低音区通常更适合开放排列，高音区可容纳更近的声部。整体移调与个别音八度折返会改变不同关系。",
        "先验证当前游戏乐器的可用键域。处理超出音域的音时，检查旋律走向、和弦声部及节奏是否仍自然。",
        "umn-orchestration",
    ),
    _Article(
        "instrument-transposition", "整体移调、折八度与乐器音域",
        "整轨移调|整段移调|整体移调|单音折八度|单个音折八度|折一组八度|折八度|八度折返|八度折叠|换乐器音域|"
        "音域更窄|高音越界|octave fold|octave folding|transpose a passage|transpose whole track|narrower range",
        "所有音同移若干半音会保住彼此的音程。单个音折八度保留其音级，却可能改变旋律轮廓、最低音或转位。"
        "只有一轨移非八度的音程时，还要检查与其他轨的和声关系。",
        "先查目标黑沙乐器的可用音域。整句同移八度且仍在音域内时优先试听此方案；若放不下，再考虑局部重排或换乐器，"
        "试听修复音前后的音程和重叠。",
        "omt-transposition",
    ),
    _Article(
        "idiomatic-articulation", "连奏、断奏、滑音与颤音",
        "奏法|连奏|断奏|滑音|滑弦|颤音|弱音|ntype|奏法值|奏法编号|原生奏法|按键奏法|手工奏法|"
        "staccato|legato|glissando|slide|trill|palm mute|articulation|articulation id",
        "连奏和断奏影响音与音的衔接。颤音通常在本音与邻音之间交替，滑音强调连续的音高运动，两者都依赖乐句与乐器语境。",
        "优先保留手工奏法。多声部和弦、跨声部以及句尾长音慎加装饰。BDO 奏法值要核对当前乐器与键域证据。",
        "bdo-articulation",
    ),
    _Article(
        "sustain-and-drum-rolls", "钢琴踏板与打击乐延续",
        "踏板|延音踏板|延音|滚奏|鼓件|鼓键|打击乐|长鼓音|鼓键 48|gm 48|gm midi 的鼓键|cc64|sustain pedal|pedal|"
        "drum roll|percussion|drum map|drum kit|hi mid tom|midi drum key",
        "GM 鼓键 48 是 Hi-Mid Tom，BDO 原生鼓键 48 是底鼓。当前 GM 导入将 GM48 映射到 BDO60（Tom5）；"
        "GM 试听另把 BDO55（Tom2）映射到 GM48。鼓键与乐器 ID 各有含义。",
        "先确认输入是 GM 鼓键还是 BDO 原生鼓键，再核对转换结果。长鼓音不能单独证明滚奏，结合明确奏法、重复起音或试听判断。"
        "钢琴已有 CC64 时保留踏板信息并核对换和声处的共鸣。",
        "bdo-drum-map",
    ),
    _Article(
        "reference-audio-alignment", "参考音频的偏移、漂移与跨小节起音",
        "参考录音|参考音频|音频对齐|对齐录音|对齐参考|整首音频|前移|固定偏移|漂移|瞬态|起音候选|新起音|横跨小节线|"
        "跨小节长音|audio alignment|reference audio|timing drift|fixed offset|onset candidate|carry in|sustained note across bar",
        "跨小节长音以原音符开始处为起音，后续小节里的延续不能当作新起音。波形突变是待核对的瞬态候选，"
        "无法单独确定音高、声部或同一演奏事件。",
        "在多个分散位置核对真实起音与对应瞬态，再判断该试固定偏移还是查速度、剪辑或局部演奏偏差。"
        "+120 与 +160 毫秒只说明两个测量值不同，既不能定全曲前移 120 毫秒，也不能定性为漂移。",
        "bdo-audio-alignment",
    ),
    _Article(
        "bdo-score-constraints", "黑沙曲谱限制与本地校验",
        "黑沙|黑色沙漠|bdo|游戏曲谱|音符上限|力度范围|游戏限制|导出|导出校验|v9|note limit|tempo limit|export|black desert",
        "已记录的黑沙作曲界面中力度范围为 0–127。账号可编辑时间轴、每乐器音符数和 BPM 上限由游戏运行时提供。",
        "把本地编码限制、账号限制和音乐建议分开核对。已有曲谱的细微起音不会因为绘制网格就必须量化。",
        "bdo-authoring",
    ),
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().translate(_MUSIC_SYMBOLS)
    words = []
    for word in _WORDS.findall(text):
        if "/" in word:
            word = "".join(word.split())
        elif len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif word.endswith(("sses", "ches", "shes", "xes", "zes")):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        words.append(word)
    return " ".join(words)


_INDEX = tuple((article, frozenset(_normalize(term) for term in article.keywords.split("|"))) for article in _ARTICLES)


def _term_weight(term: str) -> int:
    if term in _GAME_TERMS:
        return 1
    if "/" in term or term in _NOTATION:
        return 10
    return 3 + 4 * term.count(" ") if term.isascii() else 4 + min(8, len(term))


def search_music_theory(query: str, *, limit: int = 3) -> dict:
    """Search Chinese or English terms in the bundled article index."""
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_THEORY_QUERY_LENGTH:
        raise ValueError("invalid_theory_query")
    if type(limit) is not int or not 1 <= limit <= MAX_THEORY_MATCHES:
        raise ValueError("invalid_theory_limit")

    normalized = _normalize(query)
    padded = f" {normalized} "
    ranked = []
    for article, terms in _INDEX:
        weights = [
            _term_weight(term) for term in terms
            if (f" {term} " in padded if term.isascii() else term in normalized)
        ]
        if weights:
            ranked.append(((max(weights), sum(weights)), article))
    ranked.sort(key=lambda result: result[0], reverse=True)
    matches = []
    for _, article in ranked[:limit]:
        source = _SOURCES[article.source]
        source_info = {"id": article.source, "title": source.title}
        if source.url:
            source_info["url"] = source.url
        else:
            source_info["path"] = source.path
        matches.append({
            "id": article.id, "title": article.title, "summary": article.summary,
            "practice": article.practice, "source": source_info,
        })
    return {"query": query.strip(), "coverage": "local_music_theory", "matches": matches}
