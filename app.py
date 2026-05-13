import json
import os
import time
import requests as _req
from dotenv import load_dotenv

load_dotenv()
from flask import Flask, render_template, request, Response, stream_with_context, jsonify
import anthropic
from openai import OpenAI
from duckduckgo_search import DDGS
from db import init_db, get_sender_config, save_sender_config, add_history, get_history, delete_history, clear_history

app = Flask(__name__)

init_db()

# ── Paper lookup: Semantic Scholar + arXiv fallback ──

S2_API = "https://api.semanticscholar.org/graph/v1"
ARXIV_API = "http://export.arxiv.org/api/query"


def search_paper(title: str) -> dict | None:
    """Search paper by title. Try Semantic Scholar first, fall back to arXiv."""
    result = _search_s2(title)
    if result:
        return result
    return _search_arxiv(title)


def _search_s2(title: str) -> dict | None:
    """Search Semantic Scholar by paper title."""
    for attempt in range(3):
        try:
            resp = _req.get(f"{S2_API}/paper/search", params={
                "query": title,
                "limit": 1,
                "fields": "title,abstract,venue,year,authors,authors.name,authors.affiliations,externalIds",
            }, timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if data:
                    return data[0]
                return None
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < 2:
                time.sleep(1)
            continue
    return None


def _search_arxiv(title: str) -> dict | None:
    """Fallback: search arXiv API by exact title phrase."""
    import xml.etree.ElementTree as ET
    try:
        # Use quoted title for exact phrase match
        query = f'ti:"{title}"'
        resp = _req.get(ARXIV_API, params={
            "search_query": query,
            "max_results": 1,
            "sortBy": "relevance",
        }, timeout=15)
        if resp.status_code != 200:
            return None

        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        root = ET.fromstring(resp.text)
        entry = root.find("atom:entry", ns)
        if entry is None:
            return None

        found_title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
        # Verify it's actually a match (not a random result)
        if not _titles_match(title, found_title):
            return None

        abstract = (entry.findtext("atom:summary", "", ns) or "").strip().replace("\n", " ")

        authors = []
        for author_el in entry.findall("atom:author", ns):
            name = (author_el.findtext("atom:name", "", ns) or "").strip()
            affiliation = ""
            aff_el = author_el.find("arxiv:affiliation", ns)
            if aff_el is not None and aff_el.text:
                affiliation = aff_el.text.strip()
            if name:
                authors.append({"name": name, "affiliations": [affiliation] if affiliation else []})

        # Extract arxiv category as venue hint
        categories = entry.findall("atom:category", ns)
        venue_parts = [c.get("term", "") for c in categories[:2]]

        return {
            "title": found_title,
            "abstract": abstract,
            "venue": " / ".join(venue_parts) if venue_parts else "",
            "year": (entry.findtext("atom:published", "", ns) or "")[:4] or None,
            "authors": authors,
        }
    except Exception:
        return None


def _titles_match(query: str, found: str) -> bool:
    """Check if two titles are close enough (case-insensitive, ignore punctuation)."""
    import re
    def normalize(s):
        return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    q = normalize(query)
    f = normalize(found)
    # Check if one contains the other or they share >80% words
    q_words = set(q.split())
    f_words = set(f.split())
    if not q_words:
        return False
    overlap = len(q_words & f_words) / max(len(q_words), len(f_words))
    return overlap > 0.7


def get_paper_authors(paper: dict) -> list[dict]:
    """Extract all authors from a paper result."""
    authors = []
    for a in paper.get("authors", []):
        name = a.get("name", "").strip()
        if not name:
            continue
        affiliations = a.get("affiliations") or []
        authors.append({
            "name": name,
            "affiliation": affiliations[0] if affiliations else "",
        })
    return authors


# ── System prompt templates ──

SYSTEM_PROMPT_ZH = """你是一个专业的招聘助手，帮助{sender_name}撰写个性化的 LinkedIn 招聘消息。

背景：
- 发件人：{sender_name}，{sender_team}
- 联系方式：{sender_contact}
- {sender_team}在开源社区开设专项计划，邀请社区资深专家共建面向特定技术方向的生态项目

消息要求：
1. 用中文撰写，语气专业友好
2. 开头用"你好 {{名字}}，" —— 只保留名字，去掉姓氏（如 "Guokai Ma" 只用 "Guokai"，"Conglong Li" 只用 "Conglong"）
3. 提及对方在【目标社区】的具体技术贡献（根据搜索信息）
4. 介绍开源专项计划，共建面向【对方具体技术方向】的生态项目
5. 邀请联系：{sender_contact}
6. 结尾固定署名：{sender_name}  {sender_team}
7. 长度 120-160 字（不含署名）
8. 只输出消息正文，不加任何解释"""

SYSTEM_PROMPT_EN = """You are a professional recruiting assistant helping {sender_name} write personalized LinkedIn recruiting messages.

Background:
- Sender: {sender_name}, {sender_team}
- Contact: {sender_contact}
- {sender_team} runs an open-source collaboration program, inviting senior community experts to co-build ecosystem projects in specific technical areas

Message requirements:
1. Write in English, professional and friendly tone
2. Start with "Hi {{first name}}," — use first name only (e.g. "Guokai Ma" → "Guokai")
3. Mention the recipient's specific technical contributions in the target community (based on search info)
4. Introduce the open-source collaboration program for the recipient's technical area
5. Invite them to connect: {sender_contact}
6. Sign off: {sender_name} | {sender_team}
7. Length: 80-120 words (excluding signature)
8. Output only the message body, no explanations"""

# ── Academic mode system prompts ──

ACADEMIC_PROMPT_ZH = """你是一个专业的学术合作邀请助手，帮助{sender_name}撰写个性化的 LinkedIn 合作交流消息。

背景：
- 发件人：{sender_name}，{sender_team}
- 联系方式：{sender_contact}
- {sender_team}关注前沿学术研究，希望与顶级会议的研究者建立合作交流

消息要求：
1. 用中文撰写，语气专业友好，学术合作的口吻（不是招聘）
2. 开头用"你好 {{名字}}，" —— 只保留名字，去掉姓氏（如 "Guokai Ma" 只用 "Guokai"）
3. 提及对方在【目标会议】发表的具体论文和研究方向（根据提供的论文信息）
4. 说明{sender_team}在该技术方向的布局或项目，表达合作兴趣
5. 邀请联系交流：{sender_contact}
6. 结尾固定署名：{sender_name}  {sender_team}
7. 长度 120-160 字（不含署名）
8. 只输出消息正文，不加任何解释"""

ACADEMIC_PROMPT_EN = """You are a professional academic collaboration assistant helping {sender_name} write personalized LinkedIn messages to researchers.

Background:
- Sender: {sender_name}, {sender_team}
- Contact: {sender_contact}
- {sender_team} follows cutting-edge research and seeks collaboration with top-conference researchers

Message requirements:
1. Write in English, professional and collegial tone (NOT recruiting — this is about research collaboration)
2. Start with "Hi {{first name}}," — use first name only (e.g. "Guokai Ma" → "Guokai")
3. Reference the recipient's specific paper and research direction at the target conference (based on provided paper info)
4. Describe {sender_team}'s work or projects in this area, express interest in collaboration
5. Invite them to connect: {sender_contact}
6. Sign off: {sender_name} | {sender_team}
7. Length: 80-120 words (excluding signature)
8. Output only the message body, no explanations"""


def build_system_prompt(config: dict) -> str:
    mode     = config.get("mode", "community")
    language = config.get("language", "zh")
    sender   = get_sender_config()

    sender_name    = sender["name"] or "Recruiter"
    sender_team    = sender["team"] or "Talent Team"
    sender_contact = sender["contact"] or ""

    if mode == "academic":
        template = ACADEMIC_PROMPT_ZH if language == "zh" else ACADEMIC_PROMPT_EN
    else:
        template = SYSTEM_PROMPT_ZH if language == "zh" else SYSTEM_PROMPT_EN

    prompt = template.format(
        sender_name=sender_name,
        sender_team=sender_team,
        sender_contact=sender_contact,
    )

    community   = config.get("community", "").strip()
    conference  = config.get("conference", "").strip()
    focus_areas = config.get("focus_areas", "").strip()
    custom_note = config.get("custom_note", "").strip()

    extra = []
    if language == "zh":
        if community:   extra.append(f"目标社区：{community}")
        if conference:  extra.append(f"目标会议：{conference}")
        if focus_areas: extra.append(f"重点技术方向：{focus_areas}")
        if custom_note: extra.append(f"额外话术要求：{custom_note}")
        if extra:
            prompt += "\n\n【本次配置】\n" + "\n".join(extra)
    else:
        if community:   extra.append(f"Target community: {community}")
        if conference:  extra.append(f"Target conference: {conference}")
        if focus_areas: extra.append(f"Focus areas: {focus_areas}")
        if custom_note: extra.append(f"Additional requirements: {custom_note}")
        if extra:
            prompt += "\n\n[Session config]\n" + "\n".join(extra)

    return prompt


GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def search_github(name: str, community: str, github_login: str = "") -> str:
    """Search GitHub for a user, return profile + top repos summary."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    info_parts = []

    try:
        if github_login:
            # Direct lookup by username
            login = github_login
        else:
            # Search users by name
            q = f"{name} {community}" if community else name
            resp = _req.get("https://api.github.com/search/users",
                            params={"q": q, "per_page": 1}, headers=headers, timeout=10)
            if resp.status_code != 200 or not resp.json().get("items"):
                return ""
            login = resp.json()["items"][0]["login"]

        # Get user profile
        profile = _req.get(f"https://api.github.com/users/{login}",
                           headers=headers, timeout=10).json()

        bio = profile.get("bio") or ""
        company = profile.get("company") or ""
        location = profile.get("location") or ""
        followers = profile.get("followers", 0)
        public_repos = profile.get("public_repos", 0)

        info_parts.append(f"GitHub: {login} | Followers: {followers} | Repos: {public_repos}")
        if bio:
            info_parts.append(f"Bio: {bio}")
        if company:
            info_parts.append(f"Company: {company}")
        if location:
            info_parts.append(f"Location: {location}")

        # Get top repos by stars
        repos_resp = _req.get(f"https://api.github.com/users/{login}/repos",
                              params={"sort": "stars", "per_page": 5},
                              headers=headers, timeout=10)
        if repos_resp.status_code == 200:
            repos = repos_resp.json()
            top_repos = []
            for r in repos:
                stars = r.get("stargazers_count", 0)
                desc = r.get("description") or ""
                lang = r.get("language") or ""
                top_repos.append(f"  - {r['name']} ({lang}, {stars} stars): {desc[:80]}")
            if top_repos:
                info_parts.append("Top repos:\n" + "\n".join(top_repos))

    except Exception:
        pass

    return "\n".join(info_parts)


def search_person(name: str, url: str, community: str, github_login: str = "") -> str:
    """Combine GitHub API + DuckDuckGo search for background info."""
    parts = []

    # GitHub API search
    gh_info = search_github(name, community, github_login)
    if gh_info:
        parts.append(gh_info)

    # DuckDuckGo search
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
    if snippets:
        parts.append("\n".join(snippets[:5]))

    return "\n\n".join(parts)


def generate_academic_message(name: str, affiliation: str, paper_title: str,
                              abstract: str, venue: str,
                              api_key: str = "", config: dict = None) -> str:
    """Generate a collaboration message for an academic author."""
    config = config or {}
    provider   = config.get("provider", "anthropic")
    model_name = config.get("model_name", "").strip()
    base_url   = config.get("base_url", "").strip()

    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "⚠️ 未设置 API Key，请在页面顶部输入。"

    system_prompt = build_system_prompt(config)
    user_prompt = f"""请为以下研究者生成一条个性化 LinkedIn 合作交流消息：

姓名：{name}
机构：{affiliation or "未知"}
论文标题：{paper_title}
发表会议：{venue or "顶级学术会议"}
论文摘要：{abstract or "（无摘要）"}"""

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
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            resp = client.chat.completions.create(
                model=model_name or "glm-4",
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": system_prompt + "\n/no_think"},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            msg = resp.choices[0].message
            text = (msg.content or "").strip()
            if not text:
                text = getattr(msg, "reasoning", "") or ""
                text = text.strip()
            return text
    except Exception as e:
        return f"⚠️ 生成失败：{e}"


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
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            resp = client.chat.completions.create(
                model=model_name or "glm-4",
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": system_prompt + "\n/no_think"},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            msg = resp.choices[0].message
            text = (msg.content or "").strip()
            if not text:
                text = getattr(msg, "reasoning", "") or ""
                text = text.strip()
            return text

    except Exception as e:
        return f"⚠️ 生成失败：{e}"


@app.route("/")
def index():
    return render_template("index.html")


# ── Sender config API ──

@app.route("/api/sender", methods=["GET"])
def api_get_sender():
    return jsonify(get_sender_config())


@app.route("/api/sender", methods=["POST"])
def api_save_sender():
    body = request.json or {}
    save_sender_config(
        body.get("name", ""),
        body.get("team", ""),
        body.get("contact", ""),
    )
    return jsonify({"ok": True})


# ── History API ──

@app.route("/api/history", methods=["GET"])
def api_get_history():
    search = request.args.get("search", "")
    return jsonify(get_history(search=search))


@app.route("/api/history/<int:record_id>", methods=["DELETE"])
def api_delete_history(record_id):
    delete_history(record_id)
    return jsonify({"ok": True})


@app.route("/api/history/clear", methods=["POST"])
def api_clear_history():
    clear_history()
    return jsonify({"ok": True})


# ── Paper lookup API ──

@app.route("/api/lookup-paper", methods=["POST"])
def api_lookup_paper():
    """Look up a paper title via Semantic Scholar, return authors + abstract."""
    body = request.json or {}
    title = body.get("title", "").strip()
    if not title:
        return jsonify({"error": "missing title"}), 400

    paper = search_paper(title)
    if not paper:
        return jsonify({"error": "not found", "title": title}), 404

    authors = get_paper_authors(paper)
    return jsonify({
        "title":    paper.get("title", title),
        "abstract": paper.get("abstract", ""),
        "venue":    paper.get("venue", ""),
        "year":     paper.get("year"),
        "authors":  authors,
    })


# ── Academic generate API ──

@app.route("/api/generate-academic", methods=["POST"])
def generate_academic():
    body     = request.json or {}
    papers   = body.get("papers", [])
    config   = body.get("config", {})
    api_key  = request.headers.get("X-Api-Key", "")
    language = config.get("language", "zh")
    conference = config.get("conference", "")

    config["mode"] = "academic"

    def stream():
        for paper in papers:
            title    = paper.get("title", "")
            abstract = paper.get("abstract", "")
            venue    = paper.get("venue", "") or conference
            authors  = paper.get("authors", [])

            for author in authors:
                name = author.get("name", "").strip()
                if not name:
                    continue
                affiliation = author.get("affiliation", "")

                yield f"data: {json.dumps({'status': 'generating', 'name': name, 'paper': title})}\n\n"

                message = generate_academic_message(
                    name, affiliation, title, abstract, venue, api_key, config
                )

                add_history(name, "", conference, language, message)

                yield f"data: {json.dumps({'status': 'done', 'name': name, 'paper': title, 'affiliation': affiliation, 'message': message})}\n\n"

                time.sleep(0.1)  # gentle pacing for API rate limits

        yield f"data: {json.dumps({'status': 'complete'})}\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream")


# ── Generate API ──

@app.route("/api/generate", methods=["POST"])
def generate():
    body      = request.json or {}
    people    = body.get("people", [])
    config    = body.get("config", {})
    api_key   = request.headers.get("X-Api-Key", "")
    community = config.get("community", "")
    language  = config.get("language", "zh")

    def stream():
        for person in people:
            name   = person.get("name", "").strip()
            url    = person.get("url",  "").strip()
            github = person.get("github", "").strip()
            if not name:
                continue

            yield f"data: {json.dumps({'status': 'searching',  'name': name})}\n\n"
            context = search_person(name, url, community, github)

            yield f"data: {json.dumps({'status': 'generating', 'name': name})}\n\n"
            message = generate_message(name, url, context, api_key, config)

            # Save to history
            add_history(name, url, community, language, message)

            yield f"data: {json.dumps({'status': 'done', 'name': name, 'url': url, 'message': message})}\n\n"

        yield f"data: {json.dumps({'status': 'complete'})}\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream")


if __name__ == "__main__":
    print("🚀 启动中：http://localhost:5055")
    app.run(debug=False, port=5055, threaded=True)
