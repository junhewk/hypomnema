// Package ingestion handles file parsing, URL fetching, and feed polling.
package ingestion

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"
	"unicode"

	"github.com/dslipak/pdf"
	trafilatura "github.com/goto-opensource/go-trafilatura"
	"github.com/junhewk/hypomnema/internal/db"
	"github.com/mmcdole/gofeed"
)

// ParsedFile is the result of parsing an uploaded file.
type ParsedFile struct {
	Text     string
	MimeType string
	Title    string
}

// ParseFile extracts text from PDF, DOCX, or Markdown files.
func ParseFile(filename string, data []byte) (*ParsedFile, error) {
	lower := strings.ToLower(filename)
	switch {
	case strings.HasSuffix(lower, ".pdf"):
		return parsePDF(data)
	case strings.HasSuffix(lower, ".docx"):
		return parseDOCX(data)
	case strings.HasSuffix(lower, ".md") || strings.HasSuffix(lower, ".txt"):
		return &ParsedFile{
			Text:     string(data),
			MimeType: "text/markdown",
			Title:    strings.TrimSuffix(strings.TrimSuffix(filename, ".md"), ".txt"),
		}, nil
	default:
		return nil, fmt.Errorf("unsupported file type: %s", filename)
	}
}

// FetchURL downloads a URL and extracts readable text.
func FetchURL(ctx context.Context, rawURL string) (string, string, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "GET", rawURL, nil)
	if err != nil {
		return "", "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; Hypomnema/1.0)")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()

	// Check HTTP status
	if resp.StatusCode >= 400 {
		return "", "", fmt.Errorf("HTTP %d fetching %s", resp.StatusCode, rawURL)
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, 30<<20)) // 30MB limit
	if err != nil {
		return "", "", err
	}

	// Detect PDF by Content-Type or magic bytes
	ct := resp.Header.Get("Content-Type")
	isPDF := strings.Contains(ct, "application/pdf") || (len(body) > 4 && string(body[:5]) == "%PDF-")
	if isPDF {
		parsed, err := parsePDF(body)
		if err != nil {
			return "", "", fmt.Errorf("PDF parse: %w", err)
		}
		return parsed.Text, parsed.Title, nil
	}

	html := string(body)

	// Detect anti-bot / challenge pages
	if isChallengePage(html) {
		return "", "", fmt.Errorf("page is protected by anti-bot challenge (Cloudflare/etc.) and cannot be fetched")
	}

	text, title, err := extractReadableHTML(rawURL, html)
	if err == nil && len(text) >= 50 {
		return text, title, nil
	}

	// Fallback to Jina Reader for JS-rendered or paywalled pages
	jText, jTitle, jErr := fetchViaJinaReader(ctx, rawURL)
	if jErr != nil {
		if err != nil {
			return "", "", fmt.Errorf("no meaningful content extracted from %s (main extractor: %w; jina fallback: %w)", rawURL, err, jErr)
		}
		return "", "", fmt.Errorf("no meaningful content extracted from %s (jina fallback: %w)", rawURL, jErr)
	}
	return jText, jTitle, nil
}

// fetchViaJinaReader uses r.jina.ai to extract content from JS-rendered pages.
func fetchViaJinaReader(ctx context.Context, rawURL string) (string, string, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	jinaURL := "https://r.jina.ai/" + rawURL
	req, err := http.NewRequestWithContext(ctx, "GET", jinaURL, nil)
	if err != nil {
		return "", "", err
	}
	req.Header.Set("Accept", "text/plain")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return "", "", fmt.Errorf("jina HTTP %d", resp.StatusCode)
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return "", "", err
	}

	text := strings.TrimSpace(string(body))
	if len(text) < 50 {
		return "", "", fmt.Errorf("jina returned no content")
	}

	// Extract title from first markdown heading if present
	var title string
	if strings.HasPrefix(text, "# ") {
		if idx := strings.Index(text, "\n"); idx > 0 {
			title = strings.TrimPrefix(text[:idx], "# ")
		}
	} else if strings.HasPrefix(text, "Title: ") {
		if idx := strings.Index(text, "\n"); idx > 0 {
			title = strings.TrimPrefix(text[:idx], "Title: ")
		}
	}

	return text, title, nil
}

// isChallengePage detects Cloudflare, hCaptcha, and similar anti-bot challenge pages.
func isChallengePage(html string) bool {
	lower := strings.ToLower(html)
	markers := []string{
		"cf-browser-verification",
		"cf_chl_opt",
		"cf-challenge-running",
		"checking your browser",
		"just a moment",
		"enable javascript and cookies to continue",
		"hcaptcha.com",
		"challenges.cloudflare.com",
		"ray id:",
		"attention required! | cloudflare",
		"please turn javascript on",
		"ddos-guard",
	}
	for _, m := range markers {
		if strings.Contains(lower, m) {
			return true
		}
	}
	return false
}

// CheckDuplicateURL returns true if a document with this source_uri already exists.
func CheckDuplicateURL(database *db.DB, url string) (bool, error) {
	var count int
	err := database.QueryRow(`SELECT COUNT(*) FROM documents WHERE source_uri = ?`, url).Scan(&count)
	return count > 0, err
}

// FetchedItem is a single item from a feed poll.
type FetchedItem struct {
	Title     string
	Text      string
	SourceURI string
}

// PollFeed fetches new items from a feed source.
func PollFeed(ctx context.Context, feed db.FeedSource) ([]FetchedItem, error) {
	switch feed.FeedType {
	case "rss":
		return pollRSS(ctx, feed.URL)
	case "scrape":
		return pollScrape(ctx, feed.URL)
	case "youtube":
		return pollYouTube(ctx, feed.URL)
	default:
		return nil, fmt.Errorf("unknown feed type: %s", feed.FeedType)
	}
}

// ---------------------------------------------------------------------------
// PDF post-processing helpers (ported from Python reference)
// ---------------------------------------------------------------------------

var (
	pageNumberRe     = regexp.MustCompile(`(?i)^(?:page\s+)?\d+(?:\s*(?:/|of)\s*\d+)?$`)
	sentenceEndRe    = regexp.MustCompile(`[.!?][""')\]]?$`)
	backmatterHeadRe = regexp.MustCompile(`(?i)^(?:references|bibliography|appendix(?:\b|[\s:.\-])|appendices(?:\b|[\s:.\-])|acknowledg(?:e)?ments?)`)
	listOrHeadingRe  = regexp.MustCompile(`(?i)^(?:` +
		`[-*+•]\s+` +
		`|\d+[.)]\s+` +
		`|\d+(?:\.\d+)+\s+` +
		`|(?:figure|table)\s+\d+[.:]?\s+` +
		`|(?:abstract|keywords?)\b` +
		`|(?:references|bibliography|appendix|acknowledg(?:e)?ments?)\b` +
		`)`)

	backmatterMinBlocks   = 24
	backmatterMinFraction = 0.35
)

// trimBackmatter removes references/bibliography sections from the tail of
// a PDF when the document is long enough that they likely represent
// non-essential backmatter.
func trimBackmatter(blocks []string) []string {
	if len(blocks) < backmatterMinBlocks {
		return blocks
	}
	minIndex := int(float64(len(blocks)) * backmatterMinFraction)
	if minIndex < 8 {
		minIndex = 8
	}
	for i := minIndex; i < len(blocks); i++ {
		if backmatterHeadRe.MatchString(strings.TrimSpace(blocks[i])) {
			return blocks[:i]
		}
	}
	return blocks
}

// isStructuralLine detects list items, headings, references, etc.
func isStructuralLine(line string) bool {
	s := strings.TrimSpace(line)
	if s == "" {
		return false
	}
	if listOrHeadingRe.MatchString(s) {
		return true
	}
	// All-uppercase short lines (headings)
	if len(s) <= 120 {
		allUpper := true
		for _, r := range s {
			if unicode.IsLetter(r) && !unicode.IsUpper(r) {
				allUpper = false
				break
			}
		}
		if allUpper {
			return true
		}
	}
	if strings.HasPrefix(s, "[") && len(s) > 1 && s[1] >= '0' && s[1] <= '9' {
		return true
	}
	return strings.HasPrefix(strings.ToLower(s), "doi:")
}

// shouldStartNewParagraph decides whether to break before nextLine.
func shouldStartNewParagraph(current, nextLine string) bool {
	if current == "" {
		return false
	}
	if isStructuralLine(current) || isStructuralLine(nextLine) {
		return true
	}
	return sentenceEndRe.MatchString(strings.TrimSpace(current))
}

// coalescePDFLines joins single-newline-separated lines into paragraphs.
func coalescePDFLines(lines []string) []string {
	var paragraphs []string
	var current string

	for _, raw := range lines {
		line := strings.TrimSpace(raw)
		if line == "" {
			if current != "" {
				paragraphs = append(paragraphs, strings.TrimSpace(current))
				current = ""
			}
			continue
		}
		if pageNumberRe.MatchString(line) {
			continue
		}
		if current == "" {
			current = line
			continue
		}
		// Hyphenated word across lines
		if strings.HasSuffix(current, "-") && len(line) > 0 && unicode.IsLower(rune(line[0])) {
			current = current[:len(current)-1] + line
			continue
		}
		if shouldStartNewParagraph(current, line) {
			paragraphs = append(paragraphs, strings.TrimSpace(current))
			current = line
			continue
		}
		current = current + " " + line
	}
	if current != "" {
		paragraphs = append(paragraphs, strings.TrimSpace(current))
	}
	return paragraphs
}

// preprocessPDFPages takes per-page raw text slices and returns cleaned text.
func preprocessPDFPages(pageTexts []string) (string, error) {
	// Coalesce lines per page, then join into blocks.
	var allBlocks []string
	for _, pageText := range pageTexts {
		lines := strings.Split(strings.ReplaceAll(pageText, "\r", "\n"), "\n")
		var trimmed []string
		for _, l := range lines {
			trimmed = append(trimmed, strings.TrimSpace(l))
		}
		// Filter blank-only lines for coalescing (keep them as separators)
		paragraphs := coalescePDFLines(trimmed)
		for _, p := range paragraphs {
			p = strings.TrimSpace(p)
			if p != "" {
				allBlocks = append(allBlocks, p)
			}
		}
	}

	allBlocks = trimBackmatter(allBlocks)
	text := strings.Join(allBlocks, "\n\n")
	// Collapse triple+ newlines
	for strings.Contains(text, "\n\n\n") {
		text = strings.ReplaceAll(text, "\n\n\n", "\n\n")
	}
	text = strings.TrimSpace(text)
	if text == "" {
		return "", fmt.Errorf("no extractable text after PDF preprocessing")
	}
	return text, nil
}

func parsePDF(data []byte) (*ParsedFile, error) {
	// dslipak/pdf requires a file path, so write to a temp file.
	tmpFile, err := os.CreateTemp("", "hypomnema-pdf-*.pdf")
	if err != nil {
		return nil, fmt.Errorf("creating temp file for PDF: %w", err)
	}
	tmpPath := tmpFile.Name()
	defer os.Remove(tmpPath)

	if _, err := tmpFile.Write(data); err != nil {
		tmpFile.Close()
		return nil, fmt.Errorf("writing temp PDF: %w", err)
	}
	tmpFile.Close()

	reader, err := pdf.Open(tmpPath)
	if err != nil {
		return nil, fmt.Errorf("opening PDF: %w", err)
	}

	numPages := reader.NumPage()
	if numPages == 0 {
		return nil, fmt.Errorf("PDF has no pages")
	}

	pageTexts := make([]string, 0, numPages)
	for i := 1; i <= numPages; i++ {
		page := reader.Page(i)
		if page.V.IsNull() {
			pageTexts = append(pageTexts, "")
			continue
		}
		text, err := page.GetPlainText(nil)
		if err != nil {
			// Non-fatal: some pages may have no extractable text.
			pageTexts = append(pageTexts, "")
			continue
		}
		pageTexts = append(pageTexts, text)
	}

	text, err := preprocessPDFPages(pageTexts)
	if err != nil {
		return nil, err
	}

	return &ParsedFile{
		Text:     text,
		MimeType: "application/pdf",
	}, nil
}

func parseDOCX(data []byte) (*ParsedFile, error) {
	// DOCX is a ZIP archive; we need word/document.xml.
	r, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, fmt.Errorf("opening DOCX as ZIP: %w", err)
	}

	var docFile *zip.File
	for _, f := range r.File {
		if f.Name == "word/document.xml" {
			docFile = f
			break
		}
	}
	if docFile == nil {
		return nil, fmt.Errorf("word/document.xml not found in DOCX archive")
	}

	rc, err := docFile.Open()
	if err != nil {
		return nil, fmt.Errorf("opening word/document.xml: %w", err)
	}
	defer rc.Close()

	// Walk XML tokens looking for <w:p> paragraphs and <w:t> text runs.
	const wpNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
	decoder := xml.NewDecoder(rc)

	var paragraphs []string
	inParagraph := false
	inTextRun := false
	var currentPara strings.Builder

	for {
		tok, err := decoder.Token()
		if err != nil {
			if err == io.EOF {
				break
			}
			return nil, fmt.Errorf("parsing DOCX XML: %w", err)
		}
		switch t := tok.(type) {
		case xml.StartElement:
			if t.Name.Space == wpNS && t.Name.Local == "p" {
				inParagraph = true
				currentPara.Reset()
			} else if t.Name.Space == wpNS && t.Name.Local == "t" && inParagraph {
				inTextRun = true
			}
		case xml.CharData:
			if inTextRun {
				currentPara.Write(t)
			}
		case xml.EndElement:
			if t.Name.Space == wpNS && t.Name.Local == "t" {
				inTextRun = false
			} else if t.Name.Space == wpNS && t.Name.Local == "p" {
				inParagraph = false
				inTextRun = false
				text := strings.TrimSpace(currentPara.String())
				if text != "" {
					paragraphs = append(paragraphs, text)
				}
			}
		}
	}

	if len(paragraphs) == 0 {
		return nil, fmt.Errorf("no extractable text in DOCX")
	}

	return &ParsedFile{
		Text:     strings.Join(paragraphs, "\n\n"),
		MimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	}, nil
}

// pollRSS fetches and parses an RSS/Atom feed, returning one FetchedItem per entry.
func pollRSS(ctx context.Context, feedURL string) ([]FetchedItem, error) {
	fp := gofeed.NewParser()
	feed, err := fp.ParseURLWithContext(feedURL, ctx)
	if err != nil {
		return nil, fmt.Errorf("parsing RSS feed: %w", err)
	}

	var items []FetchedItem
	for _, item := range feed.Items {
		text := item.Description
		if item.Content != "" {
			text = item.Content
		}
		text = stripHTML(text)

		link := item.Link
		if link == "" && len(item.Links) > 0 {
			link = item.Links[0]
		}

		title := item.Title
		if title == "" {
			title = "Untitled"
		}

		items = append(items, FetchedItem{
			Title:     title,
			Text:      text,
			SourceURI: link,
		})
	}
	return items, nil
}

// pollScrape fetches a single web page, extracts readable text, and returns it
// as a one-element slice.
func pollScrape(ctx context.Context, pageURL string) ([]FetchedItem, error) {
	text, title, err := FetchURL(ctx, pageURL)
	if err != nil {
		return nil, err
	}
	return []FetchedItem{{Title: title, Text: text, SourceURI: pageURL}}, nil
}

// youtubeVideoIDRe matches the common YouTube URL shapes and captures the video ID.
var youtubeVideoIDRe = regexp.MustCompile(
	`(?:youtu\.be/|youtube\.com/(?:watch\?.*v=|embed/|v/))([A-Za-z0-9_-]{11})`,
)

// extractYouTubeVideoID pulls the 11-character video ID from a YouTube URL.
func extractYouTubeVideoID(rawURL string) (string, error) {
	m := youtubeVideoIDRe.FindStringSubmatch(rawURL)
	if len(m) < 2 {
		return "", fmt.Errorf("could not extract YouTube video ID from %q", rawURL)
	}
	return m[1], nil
}

// captionTrackRe extracts the captions JSON from ytInitialPlayerResponse.
var captionTrackRe = regexp.MustCompile(`"captionTracks"\s*:\s*(\[.*?\])`)

// pollYouTube fetches a YouTube video transcript by scraping the captions URL
// from the video page's embedded player response, then fetching the timedtext XML.
func pollYouTube(ctx context.Context, videoURL string) ([]FetchedItem, error) {
	videoID, err := extractYouTubeVideoID(videoURL)
	if err != nil {
		return nil, err
	}

	canonical := "https://www.youtube.com/watch?v=" + url.QueryEscape(videoID)

	// Fetch the video page
	ctx2, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx2, "GET", canonical, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; Hypomnema/1.0)")
	req.Header.Set("Accept-Language", "en-US,en;q=0.9")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetching YouTube page: %w", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 5<<20))
	if err != nil {
		return nil, err
	}
	pageHTML := string(body)

	title := extractHTMLTitle(pageHTML)
	if title == "" {
		title = "YouTube video " + videoID
	}

	// Try to extract transcript from captions
	transcript, err := extractYouTubeTranscript(ctx, pageHTML)
	if err != nil {
		// Fall back to page text if transcript unavailable
		transcript = stripHTML(pageHTML)
	}

	return []FetchedItem{{
		Title:     title,
		Text:      transcript,
		SourceURI: canonical,
	}}, nil
}

// extractYouTubeTranscript parses the captionTracks from the page HTML,
// fetches the first available transcript URL, and extracts text from the XML.
func extractYouTubeTranscript(ctx context.Context, pageHTML string) (string, error) {
	// Find captionTracks JSON in ytInitialPlayerResponse
	match := captionTrackRe.FindStringSubmatch(pageHTML)
	if len(match) < 2 {
		return "", fmt.Errorf("no caption tracks found")
	}

	// Parse the JSON array to get the base URL
	type captionTrack struct {
		BaseURL string `json:"baseUrl"`
	}
	var tracks []captionTrack
	if err := json.Unmarshal([]byte(match[1]), &tracks); err != nil {
		return "", fmt.Errorf("parsing caption tracks: %w", err)
	}
	if len(tracks) == 0 || tracks[0].BaseURL == "" {
		return "", fmt.Errorf("no caption track URLs found")
	}

	// Fetch the transcript XML
	ctx2, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx2, "GET", tracks[0].BaseURL, nil)
	if err != nil {
		return "", err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("fetching transcript: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if err != nil {
		return "", err
	}

	// Parse XML transcript: <transcript><text start="..." dur="...">text</text>...</transcript>
	return parseTranscriptXML(string(body))
}

// parseTranscriptXML extracts text content from YouTube's timedtext XML format.
func parseTranscriptXML(xmlData string) (string, error) {
	type textElement struct {
		Text string `xml:",chardata"`
	}
	type transcript struct {
		Texts []textElement `xml:"text"`
	}

	var t transcript
	if err := xml.Unmarshal([]byte(xmlData), &t); err != nil {
		return "", fmt.Errorf("parsing transcript XML: %w", err)
	}

	if len(t.Texts) == 0 {
		return "", fmt.Errorf("transcript has no text elements")
	}

	var parts []string
	for _, elem := range t.Texts {
		text := strings.TrimSpace(elem.Text)
		// Unescape HTML entities that YouTube sometimes includes
		text = strings.ReplaceAll(text, "&amp;", "&")
		text = strings.ReplaceAll(text, "&#39;", "'")
		text = strings.ReplaceAll(text, "&quot;", "\"")
		text = strings.ReplaceAll(text, "&lt;", "<")
		text = strings.ReplaceAll(text, "&gt;", ">")
		if text != "" {
			parts = append(parts, text)
		}
	}

	return strings.Join(parts, " "), nil
}

func extractHTMLTitle(html string) string {
	start := strings.Index(html, "<title>")
	if start == -1 {
		start = strings.Index(html, "<TITLE>")
	}
	if start == -1 {
		return ""
	}
	start += 7
	end := strings.Index(html[start:], "</")
	if end == -1 {
		return ""
	}
	return strings.TrimSpace(html[start : start+end])
}

func extractReadableHTML(rawURL, html string) (string, string, error) {
	opts := trafilatura.Options{
		Config:          readableHTMLConfig(),
		EnableFallback:  true,
		Focus:           trafilatura.FavorPrecision,
		ExcludeComments: true,
		HtmlDateMode:    trafilatura.Disabled,
	}

	if parsedURL, err := url.Parse(rawURL); err == nil {
		opts.OriginalURL = parsedURL
	}

	result, err := trafilatura.Extract(strings.NewReader(html), opts)
	if err != nil {
		return "", extractHTMLTitle(html), err
	}

	text := strings.TrimSpace(result.ContentText)
	title := strings.TrimSpace(result.Metadata.Title)
	if title == "" {
		title = extractHTMLTitle(html)
	}
	if text == "" {
		return "", title, fmt.Errorf("no readable content extracted")
	}
	return text, title, nil
}

func readableHTMLConfig() *trafilatura.Config {
	cfg := trafilatura.DefaultConfig()
	cfg.MinExtractedSize = 50
	return cfg
}

func stripHTML(html string) string {
	var b strings.Builder
	inTag := false
	for _, r := range html {
		switch {
		case r == '<':
			inTag = true
		case r == '>':
			inTag = false
			b.WriteRune(' ')
		case !inTag:
			b.WriteRune(r)
		}
	}
	// Collapse whitespace
	result := b.String()
	fields := strings.Fields(result)
	return strings.Join(fields, " ")
}
