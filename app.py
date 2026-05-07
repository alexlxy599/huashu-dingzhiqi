import json
import os
from flask import Flask, render_template, request, Response, stream_with_context
import anthropic
from openai import OpenAI
from duckduckgo_search import DDGS

app = Flask(__name__)

BASE_SYSTEM_PROMPT = """你是一个专业的招聘助手，帮助华为技术招聘专员 Alex 撰写个性化的 LinkedIn 招聘消息。

背景：
- 发件人：Alex Liu，华为人才生态团队
- 微信：alexlxy599
- 华为在开源社区开设专项计划，邀请社区资深专家共建面向特定技术方向的生态项目

消息要求：
1. 用中文撰写，语气专业友好
2. 开头用"你好 {名字}，" —— 只保留名字，去掉姓氏（如 "Guokai Ma" 只用 "Guokai"，"Conglong Li" 只用 "Conglong"）
3. 提及对方在【目标社区】的具体技术贡献（根据搜索信息）
4. 介绍华为开源专项计划，共建面向【对方具体技术方向】的生态项目
5. 邀请加微信：alexlxy599
6. 结尾固定署名：Alex Liu  华为人才生态团队
7. 长度 120-160 字（不含署名）
8. 只输出消息正文，不加任何解释"""


def build_system_prompt(config: dict) -> str:
    community   = config.get("community", "").strip()
    focus_areas = config.get("focus_areas", "").strip()
    custom_note = config.get("custom_note", "").strip()

    extra = []
    if community:   extra.append(f"目标社区：{community}")
    if focus_areas: extra.append(f"重点技术方向：{focus_areas}")
    if custom_note: extra.append(f"额外话术要求：{custom_note}")

    if extra:
        return BASE_SYSTEM_PROMPT + "\n\n【本次配置】\n" + "\n".join(extra)
    return BASE_SYSTEM_PROMPT


def search_person(name: str, url: str, community: str) -> str:
    community_kw = community if community else "AI open source"
    queries = [
        f"{name} {community_kw} GitHub contributions",
        f"{name} AI engineer researcher",
    ]
    snippets = []
    try:
        with DDGS() as ddgs:
            for q in queries:
                for r in ddgs.text(q, max_results=3):
                    snippets.append(r.get("body", ""))
                if len(snippets) >= 5:
                    break
    except Exception:
        pass
    return "\n".join(snippets[:5])


def generate_message(name: str, url: str, context: str,
                     api_key: str = "", config: dict = None) -> str:
    config     = config or {}
    provider   = config.get("provider", "anthropic")
    model_name = config.get("model_name", "").strip()
    base_url   = config.get("base_url", "").strip()
    community  = config.get("community", "开源社区")

    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "⚠️ 未设置 API Key，请在页面顶部输入。"

    system_prompt = build_system_prompt(config)
    user_prompt = f"""请为以下人员生成一条个性化 LinkedIn 招聘消息：

姓名：{name}
LinkedIn：{url}
背景信息：
{context if context else f"（未找到详细信息，根据 {community} 社区贡献者身份撰写）"}"""

    try:
        if provider == "anthropic":
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=model_name or "claude-opus-4-6",
                max_tokens=600,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return msg.content[0].text.strip()

        else:
            # OpenAI-compatible：GLM 本地部署 / 智谱云 API / 其他兼容接口
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            resp = client.chat.completions.create(
                model=model_name or "glm-4",
                max_tokens=600,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            return resp.choices[0].message.content.strip()

    except Exception as e:
        return f"⚠️ 生成失败：{e}"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def generate():
    body      = request.json or {}
    people    = body.get("people", [])
    config    = body.get("config", {})
    api_key   = request.headers.get("X-Api-Key", "")
    community = config.get("community", "")

    def stream():
        for person in people:
            name = person.get("name", "").strip()
            url  = person.get("url",  "").strip()
            if not name:
                continue

            yield f"data: {json.dumps({'status': 'searching',  'name': name})}\n\n"
            context = search_person(name, url, community)

            yield f"data: {json.dumps({'status': 'generating', 'name': name})}\n\n"
            message = generate_message(name, url, context, api_key, config)

            yield f"data: {json.dumps({'status': 'done', 'name': name, 'url': url, 'message': message})}\n\n"

        yield f"data: {json.dumps({'status': 'complete'})}\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream")


if __name__ == "__main__":
    print("🚀 启动中：http://localhost:5055")
    app.run(debug=False, port=5055, threaded=True)
