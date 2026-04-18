package ingestion

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return fn(req)
}

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

func TestFetchURLUsesYouTubeTranscriptPath(t *testing.T) {
	originalTransport := http.DefaultTransport
	http.DefaultTransport = roundTripFunc(func(req *http.Request) (*http.Response, error) {
		switch req.URL.String() {
		case "https://www.youtube.com/watch?v=005JLRt3gXI":
			body := `<html><head><title>Why do AI models hallucinate? - YouTube</title></head><body><script>var ytcfg = {"INNERTUBE_API_KEY":"test-key"};</script></body></html>`
			return &http.Response{
				StatusCode: 200,
				Header:     make(http.Header),
				Body:       io.NopCloser(strings.NewReader(body)),
				Request:    req,
			}, nil
		case "https://www.youtube.com/youtubei/v1/player?key=test-key":
			body := `{"captions":{"playerCaptionsTracklistRenderer":{"captionTracks":[{"baseUrl":"https://example.com/api/captions&fmt=srv3"}]}}}`
			return &http.Response{
				StatusCode: 200,
				Header:     make(http.Header),
				Body:       io.NopCloser(strings.NewReader(body)),
				Request:    req,
			}, nil
		case "https://example.com/api/captions":
			body := `<transcript><text>Hello &amp; welcome</text><text>Transcript line two</text></transcript>`
			return &http.Response{
				StatusCode: 200,
				Header:     make(http.Header),
				Body:       io.NopCloser(strings.NewReader(body)),
				Request:    req,
			}, nil
		default:
			t.Fatalf("unexpected request: %s", req.URL.String())
			return nil, nil
		}
	})
	defer func() {
		http.DefaultTransport = originalTransport
	}()

	text, title, err := FetchURL(context.Background(), "https://m.youtube.com/watch?v=005JLRt3gXI")
	if err != nil {
		t.Fatalf("FetchURL returned error: %v", err)
	}

	if title != "Why do AI models hallucinate? - YouTube" {
		t.Fatalf("unexpected title: %q", title)
	}
	if text != "Hello & welcome Transcript line two" {
		t.Fatalf("unexpected transcript text: %q", text)
	}
}
