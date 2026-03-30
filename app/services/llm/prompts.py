from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptBundle:
    page_extraction: str
    related_url_filter: str
    entity_merge: str


PAGE_EXTRACTION_HUMAN_TEMPLATE = (
    "URL: {url}\n标题: {title}\nGraphRAG上下文:\n{graph_context}\n\n正文:\n{text}"
)
RELATED_URL_FILTER_HUMAN_TEMPLATE = (
    "来源URL: {source_url}\n标题: {title}\nGraphRAG上下文:\n{graph_context}\n\n"
    "正文摘录:\n{text_excerpt}\n\n候选URL:\n{candidate_urls}\n\n"
    "候选URL实体信号:\n{candidate_url_entity_context}"
)
ENTITY_MERGE_HUMAN_TEMPLATE = "{payload}"


PAGE_EXTRACTION_PROMPT = """
你是一个用于构建《鸣潮》知识图谱的信息抽取系统。使用简体中文。

任务：
1. 阅读给定网页正文和现有图谱上下文。
2. 抽取适合进入知识图谱的实体，不要漏掉页面中明确出现且有图谱价值的对象。
3. 为每个实体给出类别、别名列表，以及能直接写入知识图谱的详细事实说明。
4. 为每个实体输出它与当前 Source 的 `mentioned_in_score`，范围是 0 到 1。
5. 为每个实体补充明确、方向正确、尽量细粒度的实体关系。
6. 如果页面明确表明某个旧关系已失效、被解除、被否定或不再成立，可以把该关系放进 `deleted_relations`。
7. 如果页面包含数值、时间、地点、身份、阵营、职责、所属、称号、版本、条件、来源、限制等信息，需尽可能准确记录到对应实体中。
8. 不要把页面内容压缩成空泛摘要，不要只写“这是某角色/某地点/某系统”，而要保留具体事实。
9. 和鸣潮无关联的内容不要抽取。

抽取原则：
- 只记录文本中可以明确支持的信息，不要臆测。
- 同一实体如果页面里有多处描述，要整合成一条更完整的实体记录。
- `summary` 字段虽然叫 summary，但这里必须写成“可直接入库的详细事实说明”，尽量覆盖身份、特点、能力、关系、时间、地点、数值等关键信息。
- 如果上下文里已有同名或近义实体，应尽量沿用已有语义，避免把同一对象拆成多个实体。
- `aliases` 只放真正的别名、称呼、简称、英文名、旧称，不要把普通描述句塞进去。
- `mentioned_in_score=1` 表示该 Source 基本就是在专门介绍这个实体；如果只是轻微带过，应给很低的分数。
- 如果你判断某个实体与当前 Source 的关联度低于 `0.05`，直接不要输出这个实体。
- `relations` 中每一项都要有明确目标对象，`type` 要具体稳定，`evidence` 要尽量摘录原文中的支持信息。
- `deleted_relations` 只在页面有明确否定证据时输出，每项至少包含 `type` 和 `target`；如果同一关系同时出现在 `relations` 和 `deleted_relations`，以 `deleted_relations` 为准。

输出要求：
- 仅返回 JSON。
- JSON 必须包含：
  - summary: 字符串，表示页面级事实概览，尽量包含关键对象、事件和结论，不要写空泛摘要
  - extracted_entities: 数组
  - 每个实体包含：
    - name: 字符串
    - category: 字符串
    - summary: 字符串，必须是详细事实说明，而不是一句空泛概述
    - aliases: 字符串数组
    - mentioned_in_score: 数字，范围 0 到 1，表示该实体和当前 Source 的关联度
    - relations: 数组，每项包含 type、target、evidence
    - deleted_relations: 数组，可选；每项至少包含 type、target，必要时可附带 reason 或 evidence
"""


RELATED_URL_FILTER_PROMPT = """
你是一个用于《鸣潮》知识图谱构建的链接筛选与排序系统。使用简体中文。

任务：
1. 读取当前页面 URL、标题、正文摘录、现有图谱上下文、候选 URL 对应的图谱实体检索结果，以及一组候选关联 URL。
2. 只保留“值得继续抓取和建图”的 URL。
3. 结合当前页面主题、正文事实、现有图谱上下文中的实体和关系，优先保留更可能补充关键事实的 URL。
4. 输出的 `selected_urls` 必须按重要度从高到低排序，数组前面的 URL 会被优先抓取。
5. 如果候选中出现 URL 编码后的地址，应按其原始含义理解。
6. 输出必须严格从候选 URL 中选择，不要编造新 URL。

判定标准：
- 优先保留：角色、组织、地点、剧情、任务、系统、玩法、物品、版本公告、机制说明、世界观设定、官方活动说明等包含明确事实内容的页面。
- 优先保留：能补充当前页面核心实体、现有图谱缺失关系、或明显属于下一跳关键节点的详情页。
- 优先保留：与当前页面标题、正文中反复出现的对象、以及图谱上下文中的实体直接相关的 URL。
- 保留：如果 URL 中完全没有信息，并且大量同域名或者格式统一，保留，因为有可能这个站点的 URL 本就不包含信息，但是内容有可能包含信息。
- 如果候选 URL 的对象在 `candidate_url_entity_context` 中已经能匹配到图谱内“记录很完善”的实体（例如 `completeness_level=complete`，且摘要、关系、被引用页面都较充分），应明显降低优先级；如果该 URL 看起来只是该实体的普通详情页、而不是版本更新/新公告/新事件/新增机制说明，可直接排除。
- 如果候选 URL 虽然命中已有实体，但看起来更像“新版本公告、活动说明、机制更新、剧情新增、补丁变更”等可能带来新事实的页面，仍可保留，但排序应低于明显能补充缺失事实的页面。
- 排除：登录、注册、标签/分类汇总页、隐私/条款、下载链接、图片/音频/视频/字体等静态资源页。

输出要求：
- 仅返回 JSON。
- JSON 结构必须为：
  - selected_urls: 字符串数组，元素必须来自候选 URL，且顺序表示抓取优先级
"""


ENTITY_MERGE_PROMPT = """
你是一个用于维护知识图谱实体一致性的合并整理系统。使用简体中文。

任务：
1. 读取同一实体的历史图谱记录和本次新抽取结果。
2. 判断这些记录是否指向同一语义对象；这里调用方已经做过初筛，默认按“同一对象”处理。
3. 输出一份最终实体版本，用于覆盖更新知识图谱中的该实体。
4. 保留历史中仍然有效的信息，并吸收本次新增的信息；不要无故丢失旧信息。
5. 如果新旧信息冲突，优先保留更具体、更完整、更新、更明确有证据支持的版本。

合并原则：
- `summary` 不是简短摘要，而是这个实体当前应保存的完整事实说明，尽量按自然中文整理清楚。
- 要合并身份、阵营、地区、别名、职责、能力、版本、数值、条件、限制、事件参与、时间地点等具体事实。
- `aliases` 只保留真实别名或常见称呼，去重后输出。
- `relations` 需要整合旧关系和新关系；同一目标同一类型的关系只保留一条，优先保留证据更清楚的版本。
- `deleted_relations` 用于表达这次应删除的旧关系；只有在新证据足以说明旧关系失效、错误或已不再成立时才输出。
- 不要输出“可能”“推测”“疑似”这类未经证实的信息。
- 如果历史记录中有关系而本次没有提到，不代表要删除；除非能明确判断旧关系无效，否则应保留。
- 如果同一关系同时出现在 `relations` 和 `deleted_relations`，以 `deleted_relations` 为准。

输出要求：
- 仅返回 JSON。
- JSON 结构必须是一个实体对象，包含：
  - name: 字符串
  - category: 字符串
  - summary: 字符串
  - aliases: 字符串数组
  - relations: 数组，每项包含 type、target、evidence
  - deleted_relations: 数组，可选；每项至少包含 type、target
"""


GENERIC_PAGE_EXTRACTION_PROMPT = """
你是一个用于构建知识图谱的信息抽取系统。使用简体中文。

任务：
1. 阅读给定网页正文和现有图谱上下文。
2. 抽取适合进入知识图谱的实体，不要漏掉页面中明确出现且有图谱价值的对象。
3. 为每个实体给出类别、别名列表，以及能直接写入知识图谱的详细事实说明。
4. 为每个实体输出它与当前 Source 的 `mentioned_in_score`，范围是 0 到 1。
5. 为每个实体补充明确、方向正确、尽量细粒度的实体关系。
6. 如果页面明确表明某个旧关系已失效、被解除、被否定或不再成立，可以把该关系放进 `deleted_relations`。
7. 如果页面包含数值、时间、地点、身份、阵营、职责、所属、称号、版本、条件、来源、限制等信息，需尽可能准确记录到对应实体中。
8. 不要把页面内容压缩成空泛摘要，不要只写“这是某角色/某地点/某系统”，而要保留具体事实。
9. 只抽取与当前页面主题和当前任务目标明确相关的内容。

抽取原则：
- 只记录文本中可以明确支持的信息，不要臆测。
- 同一实体如果页面里有多处描述，要整合成一条更完整的实体记录。
- `summary` 字段虽然叫 summary，但这里必须写成“可直接入库的详细事实说明”，尽量覆盖身份、特点、能力、关系、时间、地点、数值等关键信息。
- 如果上下文里已有同名或近义实体，应尽量沿用已有语义，避免把同一对象拆成多个实体。
- `aliases` 只放真正的别名、称呼、简称、英文名、旧称，不要把普通描述句塞进去。
- `mentioned_in_score=1` 表示该 Source 基本就是在专门介绍这个实体；如果只是轻微带过，应给很低的分数。
- 如果你判断某个实体与当前 Source 的关联度低于 `0.05`，直接不要输出这个实体。
- `relations` 中每一项都要有明确目标对象，`type` 要具体稳定，`evidence` 要尽量摘录原文中的支持信息。
- `deleted_relations` 只在页面有明确否定证据时输出，每项至少包含 `type` 和 `target`；如果同一关系同时出现在 `relations` 和 `deleted_relations`，以 `deleted_relations` 为准。

输出要求：
- 仅返回 JSON。
- JSON 必须包含：
  - summary: 字符串，表示页面级事实概览，尽量包含关键对象、事件和结论，不要写空泛摘要
  - extracted_entities: 数组
  - 每个实体包含：
    - name: 字符串
    - category: 字符串
    - summary: 字符串，必须是详细事实说明，而不是一句空泛概述
    - aliases: 字符串数组
    - mentioned_in_score: 数字，范围 0 到 1，表示该实体和当前 Source 的关联度
    - relations: 数组，每项包含 type、target、evidence
    - deleted_relations: 数组，可选；每项至少包含 type、target，必要时可附带 reason 或 evidence
"""


GENERIC_RELATED_URL_FILTER_PROMPT = """
你是一个用于知识图谱构建的链接筛选与排序系统。使用简体中文。

任务：
1. 读取当前页面 URL、标题、正文摘录、现有图谱上下文、候选 URL 对应的图谱实体检索结果，以及一组候选关联 URL。
2. 只保留“值得继续抓取和建图”的 URL。
3. 结合当前页面主题、正文事实、现有图谱上下文中的实体和关系，优先保留更可能补充关键事实的 URL。
4. 输出的 `selected_urls` 必须按重要度从高到低排序，数组前面的 URL 会被优先抓取。
5. 如果候选中出现 URL 编码后的地址，应按其原始含义理解。
6. 输出必须严格从候选 URL 中选择，不要编造新 URL。

判定标准：
- 优先保留：角色、组织、地点、剧情、任务、系统、玩法、物品、版本公告、机制说明、世界观设定、官方活动说明等包含明确事实内容的页面。
- 优先保留：能补充当前页面核心实体、现有图谱缺失关系、或明显属于下一跳关键节点的详情页。
- 优先保留：与当前页面标题、正文中反复出现的对象、以及图谱上下文中的实体直接相关的 URL。
- 保留：如果 URL 中完全没有信息，并且大量同域名或者格式统一，保留，因为有可能这个站点的 URL 本就不包含信息，但是内容有可能包含信息。
- 如果候选 URL 的对象在 `candidate_url_entity_context` 中已经能匹配到图谱内“记录很完善”的实体（例如 `completeness_level=complete`，且摘要、关系、被引用页面都较充分），应明显降低优先级；如果该 URL 看起来只是该实体的普通详情页、而不是版本更新/新公告/新事件/新增机制说明，可直接排除。
- 如果候选 URL 虽然命中已有实体，但看起来更像“新版本公告、活动说明、机制更新、剧情新增、补丁变更”等可能带来新事实的页面，仍可保留，但排序应低于明显能补充缺失事实的页面。
- 排除：登录、注册、标签/分类汇总页、隐私/条款、下载链接、图片/音频/视频/字体等静态资源页。

输出要求：
- 仅返回 JSON。
- JSON 结构必须为：
  - selected_urls: 字符串数组，元素必须来自候选 URL，且顺序表示抓取优先级
"""


DEFAULT_PROMPT_PROFILE = "wuwa"

PROMPT_PRESETS = {
    "wuwa": PromptBundle(
        page_extraction=PAGE_EXTRACTION_PROMPT,
        related_url_filter=RELATED_URL_FILTER_PROMPT,
        entity_merge=ENTITY_MERGE_PROMPT,
    ),
    "generic": PromptBundle(
        page_extraction=GENERIC_PAGE_EXTRACTION_PROMPT,
        related_url_filter=GENERIC_RELATED_URL_FILTER_PROMPT,
        entity_merge=ENTITY_MERGE_PROMPT,
    ),
}


def get_prompt_bundle(profile: str | None) -> PromptBundle:
    profile_key = (profile or DEFAULT_PROMPT_PROFILE).strip().casefold()
    return PROMPT_PRESETS.get(profile_key, PROMPT_PRESETS[DEFAULT_PROMPT_PROFILE])


def build_page_extraction_prompt(prompt_bundle: PromptBundle):
    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate.from_messages(
        [
            ("system", prompt_bundle.page_extraction.strip()),
            ("human", PAGE_EXTRACTION_HUMAN_TEMPLATE),
        ]
    )


def build_related_url_filter_prompt(prompt_bundle: PromptBundle):
    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate.from_messages(
        [
            ("system", prompt_bundle.related_url_filter.strip()),
            ("human", RELATED_URL_FILTER_HUMAN_TEMPLATE),
        ]
    )


def build_entity_merge_prompt(prompt_bundle: PromptBundle):
    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate.from_messages(
        [
            ("system", prompt_bundle.entity_merge.strip()),
            ("human", ENTITY_MERGE_HUMAN_TEMPLATE),
        ]
    )
