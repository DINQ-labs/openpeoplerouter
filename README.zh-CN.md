# OpenPeopleRouter

**开源的 MCP 找人路由：用你自己的数据供应商账号去找人、找公司。** 自带 key，不经过任何中间商。

- **7 个任务工具**，agent 不需要了解任何供应商就能直接用：`find_people`、`enrich_person`、`find_contact`、`verify_email`、`find_companies`、`enrich_company`、`read_profile`。
- **68 家供应商、2,200 多个接口**：B2B 人员和公司数据、邮箱查找与验证、电话数据、学术和开发者资料、各大社媒平台、网页搜索和抓取。完整清单见 [docs/providers.md](docs/providers.md)。
- **key 是你的，账单也是你的。** 每家供应商直接向你自己的账号计费。key 只存在你本地的环境变量里，所有返回结果都会把 key 抹掉。
- **一家供应商就是一个 YAML 文件**，新增供应商不用写 Python。

## 运行

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/DINQ-labs/openpeoplerouter && cd openpeoplerouter
uv sync
cp .env.example .env          # 只填你要用的供应商
uv run openpeoplerouter providers
uv run openpeoplerouter run find_contact "full_name=Jane Doe" company_domain=example.com
```

有几个数据源不需要 key 就能用：OpenAlex、ORCID、Crossref、Wikidata、GitHub、Hugging Face、Semantic Scholar、Stack Exchange、Bluesky。所以什么都不配置也能先用起来。

### 接入 MCP 客户端

默认用 stdio：

```json
{
  "mcpServers": {
    "openpeoplerouter": {
      "command": "uv",
      "args": ["--directory", "/你的绝对路径/openpeoplerouter", "run", "openpeoplerouter", "serve"]
    }
  }
}
```

也可以用 HTTP 提供给自己的其他工具：

```bash
OPENPEOPLEROUTER_TOKEN=换成你的口令 uv run openpeoplerouter serve --transport http --host 0.0.0.0 --port 8080
```

客户端连接 `http://主机:8080/mcp`，并带上 `Authorization: Bearer 你的口令`。因为调用会花你自己的供应商额度，没设口令时服务只会监听本机。用 `docker compose up` 也一样。

## 工具

| 工具 | 作用 |
| --- | --- |
| `find_people` | 按职位、公司、地点、技能或一句描述找人。`audience` 可选职场人士（默认）、研究者、开发者、创作者。多家结果会合并去重。 |
| `enrich_person` | 用邮箱、LinkedIn 链接、电话或「姓名 + 公司」补全一个人的资料。 |
| `find_contact` | 找一个人的工作邮箱和电话。 |
| `verify_email` | 检查一个邮箱能不能收信。 |
| `find_companies` | 按行业、地点、规模、技术栈或一句描述找公司。 |
| `enrich_company` | 用域名、公司名或 LinkedIn 主页补全一家公司的资料。 |
| `read_profile` | 读取 LinkedIn、X、Instagram、TikTok、YouTube、GitHub、Bluesky、Threads 等平台上的公开主页。 |
| `providers` | 查看哪些供应商已配置，以及每家读取哪个环境变量。 |
| `search_operations` | 按关键词搜索所有供应商的接口。 |
| `describe_operation` | 查看某个接口的参数、价格和文档。 |
| `call_operation` | 用供应商自己的参数直接调用接口，返回原始结果。 |

每次任务调用都会在 `tried` 里列出试过的每个接口：有没有结果、耗时多少、失败的话错在哪。agent 能据此分清「没找到这个人」「key 被拒」「额度用完」这几种情况。

## 选择供应商

```dotenv
# 只允许调用这些供应商（默认：所有配了 key 的，加上不需要 key 的）
OPENPEOPLEROUTER_PROVIDERS=hunter,apollo,openalex
# 优先按这个顺序试，其余按价格从低到高
OPENPEOPLEROUTER_ORDER=apollo,hunter
```

单次调用也可以传 `providers: ["pdl", "lusha"]`，只用这几家并按这个顺序；传 `raw: true` 还会在整理后的字段旁边附上各家返回的完整原始记录。

## 命令行

```bash
openpeoplerouter serve [--transport stdio|http] [--host] [--port]
openpeoplerouter providers [--markdown]
openpeoplerouter check                     # 校验所有供应商文件
openpeoplerouter run <任务> key=value ...   # 跑一次任务
openpeoplerouter call <供应商.接口> key=value ...
```

能按 JSON 解析的值会按 JSON 发送，比如 `limit=5`、`filters='{"x":1}'`。

## 新增供应商

按 [docs/provider-format.md](docs/provider-format.md) 写一个 `src/openpeoplerouter/providers/<id>.yaml`。供应商提供 OpenAPI 文档的话，可以先用 `scripts/from_openapi.py` 生成接口草稿。写完跑一下 `openpeoplerouter check` 和 `uv run pytest`，再提 PR。

供应商定义描述的是各家公开的 API 文档。大部分路由都对照过官方文档和返回结构；不需要 key 和提供测试 key 的供应商还做过真实调用。如果哪家改了 API，通常只需要改它文件里的一行。

## 合规使用

请遵守各供应商的服务条款，以及你和被查询者所在地的法律，包括 GDPR、CCPA 等数据保护法规。有些供应商还有自己的限制，例如某些电话数据不属于消费者报告，不能用于信贷、保险、雇佣或住房相关的决定。

## 许可证

Apache-2.0
