package ingestion

import (
	"strings"
	"testing"
)

func TestExtractReadableHTMLPrefersMainContent(t *testing.T) {
	html := `<!doctype html>
<html>
<head>
	<title>Example Article</title>
</head>
<body>
	<header>
		<nav>Home Pricing Docs Login</nav>
	</header>
	<main>
		<article>
			<h1>How public libraries work after midnight</h1>
			<p>The night staff reorganized the returns cart, documented every damaged spine, and logged quiet maintenance tasks for the morning crew.</p>
			<p>After midnight, the building shifted from public service to preservation work, with one librarian checking humidity while another repaired the local history shelf.</p>
		</article>
	</main>
	<footer>Subscribe for product updates and cookie preferences.</footer>
	<script>
		window.__INITIAL_STATE__ = {"token":"secret-script-payload","debug":"javascript should never appear in extracted text"};
	</script>
</body>
</html>`

	text, title, err := extractReadableHTML("https://example.com/article", html)
	if err != nil {
		t.Fatalf("extractReadableHTML returned error: %v", err)
	}

	if title == "" {
		t.Fatal("expected non-empty title")
	}
	if !strings.Contains(text, "The night staff reorganized the returns cart") {
		t.Fatalf("expected article text in output, got %q", text)
	}
	if strings.Contains(text, "secret-script-payload") || strings.Contains(text, "javascript should never appear") {
		t.Fatalf("script content leaked into extracted text: %q", text)
	}
	if strings.Contains(text, "Home Pricing Docs Login") {
		t.Fatalf("navigation boilerplate leaked into extracted text: %q", text)
	}
}
