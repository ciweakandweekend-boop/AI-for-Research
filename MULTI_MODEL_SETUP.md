# 五个 Agent，五个不同模型

在项目目录运行命令：`C:\AI应用demo\agent-literature-review`。

当前本地配置的显示姓名是 `Sally`。如需更换姓名，修改 `config.yaml` 的 `user.name`，例如 `name: Sally`；这个字段不是 API Key，也不会影响模型路由。

| Agent | 保留的研究角色 | 模型 | 接口平台 | config.yaml 中 Key 的位置 |
| --- | --- | --- | --- | --- |
| Lea | Biologist | `openai/gpt-oss-120b` | Groq | `api_keys.groq` |
| Emmy | Mathematician / Critical Reviewer | `gemini-3.8-flash` | Google Gemini | `api_keys.gemini` |
| Marie | Physicist / Skeptical Reviewer | `glm-4.7-flash` | 智谱 BigModel | `api_keys.zhipu` |
| Ada | Computer Scientist | `claude-sonnet-4-6` | Anthropic | `anthropic_api_key`（已有） |
| Cassandra | PI (Principal Investigator) | `qwen3.8-max` | 阿里云百炼北京区 | `api_keys.qwen` |

角色和模型是独立配置的。你可以在 `agents` 中调整角色描述或更换模型；每位 Agent 有自己的 provider、model 和凭证选择。共享讨论历史、调度和论文阅读流程继续由本地 Python 程序管理。

Emmy 和 Marie 保留原学科身份，同时通过 `system_prompt` 添加审稿任务。Emmy 检查证据、方法、引用和过度结论；Marie 检查无支持结论、方法缺陷、混淆变量和缺失证据。自定义指令会加入所有五类响应入口的系统提示；它们是角色指令，尚未实现自动核验引用的 Evidence Validator。

## 填写 Key

打开 `config.yaml`，只填写仍为空的配置项，保留已填入的 Qwen、Claude 和 Groq Key：

```yaml
api_keys:
  groq: "在本地填入 Groq Key"
  qwen: "保留已填入的百炼北京区 Key"
  zhipu: "在本地填入智谱 BigModel Key"
  gemini: "在本地填入 Google AI Studio 的 Gemini Key"
```

Lea 通过 Groq 调用 GPT-OSS-120B，使用独立的 Groq Key；模型 ID 中的 `openai/` 是模型名称的一部分，此处不需要 OpenAI API Key。Emmy 使用 Gemini Key，Marie 使用智谱 BigModel Key，当前五模型配置无需 NVIDIA Key。旧 NVIDIA 配置仍受支持，但不能把 NVIDIA Key 用于 Google 或智谱平台。模型权限、免费额度、限流以各自账号控制台为准。

- [Groq：获取 API Key](https://console.groq.com/keys)
- [GPT-OSS-120B：Groq 官方模型说明](https://console.groq.com/docs/model/openai/gpt-oss-120b)
- [Google AI Studio：获取 Gemini Key](https://aistudio.google.com/apikey)
- [Gemini 3.8 Flash 官方模型说明](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [智谱 BigModel：获取 API Key](https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys)
- [GLM-4.7-Flash 官方模型说明](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash)
- [百炼获取 API Key](https://help.aliyun.com/zh/model-studio/get-api-key)：选择与配置一致的华北2（北京）地域。
- [Qwen3.8-Max 官方模型说明](https://help.aliyun.com/zh/model-studio/qwen3-8-max)

`config.yaml` 已被 Git 忽略。Key 只填在本地文件或环境变量中，不需要发到聊天里。

也可以让四个配置项保持空字符串，在当前 PowerShell 会话中设置环境变量：

```powershell
$env:GROQ_API_KEY = "你的 Groq Key"
$env:GEMINI_API_KEY = "你的 Gemini Key"
$env:ZHIPU_API_KEY = "你的智谱 BigModel Key"
$env:DASHSCOPE_API_KEY = "你的百炼北京区 Key"
```

`GROQ_API_KEY`、`GEMINI_API_KEY`、`ZHIPU_API_KEY` 分别对应 `api_keys.groq`、`api_keys.gemini`、`api_keys.zhipu`。Qwen 支持 `QWEN_API_KEY` 或 `DASHSCOPE_API_KEY`。优先级为：模型专用环境变量 → `api_keys` 中对应值 → 平台共享环境变量。Claude 支持 `ANTHROPIC_API_KEY`，也兼容原先的 `anthropic_api_key` 配置。

## 检查和运行

先运行离线检查；它只检查配置与 Key 是否存在，不发送请求、不检验 Key 真伪、不产生 API 费用：

```powershell
python -m src.main --config config.yaml --check-config
```

缺少 Key 时，会列出 Agent、模型和需要填写的位置，退出码为 2。填齐后显示 `All keys are present`。本次切换后的本地检查记录在 `outputs/gemini_zhipu_config_check.txt`；旧检查记录保留作历史参考。

填齐后启动真实讨论：

```powershell
python -m src.main --config config.yaml
```

启动时会显示每个 Agent 的 provider/model。可先在不同轮次分别输入 `@Lea: Reply OK.`、`@Emmy: Reply OK.`、`@Marie: Reply OK.`、`@Ada: Reply OK.`、`@Cassandra: Reply OK.` 以逐一确认访问。原程序会自动安排部分协作追问，因此一条输入可能触发额外调用。

如果某个兼容 API 暂时返回 HTTP 5xx（例如 Gemini 的 503），程序会使用指数退避重试，并在终端显示重试进度；重试仍失败时只跳过该 Agent，其他 Agent 继续运行。503 是服务端暂时不可用，不是 API key 格式错误；若持续出现，应在对应平台确认模型 ID、区域/权限和服务状态。协作 follow-up 会把当前被提及的消息片段直接传给目标 Agent，避免出现 `I don't have any messages ...` 的空收件箱提示。

不带 `--output` 时，所有终端输出和用户输入自动写入 `outputs/session_YYYYMMDD_HHMMSS.txt`。每次启动都会生成一个新的时间戳文件：

```powershell
python -m src.main --config config.yaml
```

只有在需要自定义文件名时才传入 `--output`。

## 调用行为与限制

- Groq 请求地址：`https://api.groq.com/openai/v1/chat/completions`，参见[Groq 接口说明](https://console.groq.com/docs/openai)。无需安装新 SDK。
- Gemini 请求地址：`https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`，使用 `Authorization: Bearer` 和 Gemini Key，参见[Google 官方兼容接口](https://ai.google.dev/gemini-api/docs/openai)。Emmy 按配置使用 `reasoning_effort: high`。
- 智谱请求地址：`https://open.bigmodel.cn/api/paas/v4/chat/completions`，参见[智谱官方兼容接口](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)。Marie 的 `extra_body` 设置 `thinking: {type: enabled}` 和 `temperature: 0.2`；HTTP 请求时这两个参数都在请求体顶层，等价于用户提供的 SDK 示例。
- Qwen 默认使用北京区地址 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`。官方仍支持此地址，同时推荐业务空间域名；如需迁移，在 Cassandra 的 `base_url` 填入控制台地址（保留到 `/v1`，不要包含 `/chat/completions`）。Key 与地域必须匹配。参见[百炼接口说明](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。
- 普通讨论、直接回复、文档分析、检索后的回复和 PI 专用提示均调用同一适配层，不会自动换成另一个模型。
- 本次默认非流式调用。Lea 的配置不变：输出上限 2048，`reasoning_effort: low`，`include_reasoning: false`（不返回推理文本，但仍进行推理）。配置中的 `max_tokens` 会转换为 Groq API 的 `max_completion_tokens`。Emmy 和 Marie 保留 16384 的输出 Token 上限；Qwen 的关闭思考配置保持不变。可在每位 Agent 下修改 `max_tokens`、`timeout`（秒，默认 180）和 `extra_body`。推理较强时可能更慢，仍需用真实论文验证延迟与输出是否完整。
- [Google 价格页](https://ai.google.dev/gemini-api/docs/pricing)列出 Gemini 3.8 Flash 的 Free Tier；[智谱模型页](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash)将 GLM-4.7-Flash 列为免费模型。免费不等于无请求限制，账号权限和速率限制仍须在各平台确认；项目不会据此假设所有账号的账单均为零。
- 截至 2026-09-16，[Groq 免费档限额表](https://console.groq.com/docs/rate-limits)列出此模型 30 RPM、1000 RPD、8000 TPM、200000 TPD；具体以账号 Limits 为准。8000 TPM 是每分钟 Token 限额，长论文或多轮共享历史可能触发它。降低输出上限不保证长输入能通过；当前未增加论文分块或输入裁剪。
- 只把最终 `content` 加入讨论，不把 `reasoning_content` 当作回答。若没有最终文本，会显示错误；如果达到输出上限，会标记回答可能不完整。
- HTTP 401/403/404 会明确提示 Key、权限或模型配置问题；不会把服务器原始错误正文或 Key 写入日志。已有重试路径仅对临时连接错误、限流等继续重试。
- Token 统计使用 API 返回的 usage。没有已核验价格的模型显示 `price not configured`，不套用 Claude 的费用；实际账单查看各平台。
- 当前 `/read_folder` 仍提取 PDF 文本，尚未把页面图片传入视觉模型，也未增加 evidence cards 或 Evidence Validator。接入支持视觉的模型不会自动增加 PDF 图表解析功能。
- 多个模型的真实连通性需要填入新 Key 后测试；离线测试不证明免费端点可用、账号有权限或模型回答质量达标。

## 离线回归测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试模拟 API 响应，覆盖五个模型的所有五类响应入口、各自 Key 与 URL、共享上下文、原单-Claude 配置兼容、缺 Key 检查、错误处理及 usage 统计。不会调用外部模型。
