"""第三方外部集成（Zotero / Colab / experiment 等）的入口包。

每个子包暴露一个 standalone NDJSON stdio MCP server + REST/HTTP client；
凭据统一走 .env / os.environ 解析，不进 MCP server 配置文件。
"""
