阐明：
1. 目前新采集任务是如何和旧采集任务采集到的Entity和page/source联系在一起的？为什么新采集任务后能够让新的entity与旧entity产生新relation，模型是如何找到这些旧entity的，详细解释。


修复BUG:
1. [x] 目前采集信息的时候可能出现同一实体多次采集时创建重复内容非常相似的relation，想办法解决，让已经存在类似relation时不要创建新的
2. [x] 目前有些网页可能有不同语言版本或者url不同，内容完全相同，保证不会重复创建Page（可以使用向量相似度查重等）。并且如果页面判断重复，则把新url合并入Page节点，防止下次遇到重复进入，绕过TTL跳过
3. [x] 删除目前独立的Embedding节点，改成neo4j自己的向量索引构造方式，让embedding成为节点的字段，但保留RelationEmbedding。注意因为社区版没有GenAI，只能自己调用embedding api并写入节点，必须保证embedding在节点内容更新后也同步，特别是来自采集任务的更新。
4. [x] 已把图谱中的 `Page` label 重构为 `Source`，并同步完成相关代码改名
5. [x] 目前Source和Entity有MENTIONED_IN的关系，但是不能判断两者的关联度。新增一个0-1的关联度评分，让LLM判断两者的关联性。比如如果一个Source是专门介绍Entity的，关联度应该是1。如果只是提到了一点点，可以按程度设关联度为0.01或者直接不加MENTIONED_IN关系。这一段可以写进PROMPT里。对于旧的关系，使用migration进行更新，默认设置为0.5。在后续对页面进行重新采集时，这个关联度也要被更新。

FEATURE:
0. 让aliases中所有中文都有对应的中文拼音作为别名，通过LLM处理时实现。
1. 一个综合管理本地数据的服务，提供接口给本项目各类未来服务保存数据的功能(json)，支持本地部署和docker挂载的/data文件夹（通过env判断docker环境，如果是docker环境使用/docker，本地就存当前目录的./data文件夹）
2. 将配置移到前端，动态更新，存在本地（用上面那个服务），有版本控制，migration。并且让prompt也可以自定义（不需要wuwa预设了）。前端需要做分组分类，人性化的配置页面。(Gemini 3 pro)将Neo4J和LLM数据源分离（可以独立创建多个Neo4J和LLM配置，在配置文件里可以选择所有定义好的数据源作为embedding模型，llm模型等）
3. 前后端需要做验证，环境变量可以设置入口密码，使用argon2id做密码增强，前端必须输入密码才能进入管理页面，后端也要做校验
4. 删除InMemoryJobStore，保留vectorindexjob
5. 一套APIKey生成，统计，管理逻辑（后端GPT5,前端Gemini3pro），用于调用未来的查询接口。用本地数据服务进行存储和读取。
6. 提供一套查询接口，可以选择数据源，实现查询neo4j的entity,Source对象，再加上综合性的查找
7. 配置预设系统。

安全性：
防止查询内容造成注入