from app.services.crawl.extractor import ContentExtractor


def test_extractor_prefers_main_content_and_removes_fandom_noise():
    extractor = ContentExtractor()
    html = """
    <html>
      <head>
        <title>角色己 | 示例 Wiki | Fandom</title>
      </head>
      <body>
        <nav>
          <a href="/signin">创建免费账户</a>
          <a href="/privacy">隐私政策</a>
        </nav>
        <main class="page__main">
          <div id="mw-content-text" class="mw-body-content">
            <div class="mw-parser-output">
              <aside class="portable-infobox">
                <h2>角色己</h2>
                <div class="pi-data-value">组织庚</div>
              </aside>
              <p><b>角色己</b>是示例设定中的角色。组织庚的负责人。</p>
              <h2>变更历史</h2>
              <p>於版本 3.1 引入。</p>
            </div>
          </div>
        </main>
        <footer>
          <a href="/privacy">隐私政策</a>
        </footer>
        <script>window.fandomCmp = {};</script>
      </body>
    </html>
    """

    result = extractor.extract(
        url="https://fictional.example.fandom.com/zh/wiki/%E8%A7%92%E8%89%B2%E5%B7%B1",
        canonical_url="https://fictional.example.fandom.com/zh/wiki/%E8%A7%92%E8%89%B2%E5%B7%B1",
        status_code=200,
        fetch_mode="browser",
        html=html,
        links=[],
    )

    assert result.title == "角色己 | 示例 Wiki | Fandom" or result.title == "角色己"
    assert "角色己" in result.text
    assert "组织庚的负责人" in result.text
    assert "隐私政策" not in result.text
    assert "创建免费账户" not in result.text
    assert "window.fandomCmp" not in result.text


def test_extractor_falls_back_to_article_when_mediawiki_container_is_empty():
    extractor = ContentExtractor()
    html = """
    <html>
      <head>
        <title>羽丘女子学园</title>
      </head>
      <body>
        <div id="mw-content-text">
          <div class="mw-parser-output"></div>
        </div>
        <main>
          <article>
            <h1>羽丘女子学园</h1>
            <p>羽丘女子学园是《BanG Dream!》中的主要学校之一。</p>
            <p>这里是多名核心角色的活动舞台。</p>
          </article>
        </main>
      </body>
    </html>
    """

    result = extractor.extract(
        url="https://mzh.moegirl.org.cn/%E7%BE%BD%E4%B8%98%E5%A5%B3%E5%AD%90%E5%AD%A6%E5%9B%AD",
        canonical_url="https://mzh.moegirl.org.cn/%E7%BE%BD%E4%B8%98%E5%A5%B3%E5%AD%90%E5%AD%A6%E5%9B%AD",
        status_code=200,
        fetch_mode="browser",
        html=html,
        links=[],
    )

    assert "羽丘女子学园是《BanG Dream!》中的主要学校之一。" in result.text
    assert "这里是多名核心角色的活动舞台。" in result.text


def test_extractor_falls_back_to_whole_page_text_when_common_roots_are_empty():
    extractor = ContentExtractor()
    html = """
    <html>
      <head>
        <title>整页回退示例</title>
      </head>
      <body>
        <nav>
          <a href="/privacy">隐私政策</a>
        </nav>
        <div id="app"></div>
        <section class="page-shell">
          <div>这是整页回退拿到的正文。</div>
          <div>当常见正文容器为空时，应该至少保留这些文本。</div>
        </section>
        <footer>页脚链接</footer>
      </body>
    </html>
    """

    result = extractor.extract(
        url="https://example.com/fallback-page",
        canonical_url="https://example.com/fallback-page",
        status_code=200,
        fetch_mode="browser",
        html=html,
        links=[],
    )

    assert "这是整页回退拿到的正文。" in result.text
    assert "当常见正文容器为空时，应该至少保留这些文本。" in result.text
    assert "隐私政策" not in result.text
    assert "页脚链接" not in result.text
