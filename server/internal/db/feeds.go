package db

type FeedSource struct {
	ID          string  `json:"id"`
	Name        string  `json:"name"`
	FeedType    string  `json:"feed_type"`
	URL         string  `json:"url"`
	Schedule    string  `json:"schedule"`
	Active      int     `json:"active"`
	LastFetched *string `json:"last_fetched"`
	CreatedAt   string  `json:"created_at"`
}

func (db *DB) InsertFeed(f *FeedSource) error {
	if f.ID == "" {
		f.ID = NewID()
	}
	if f.Schedule == "" {
		f.Schedule = "0 */6 * * *"
	}
	f.CreatedAt = Now()

	_, err := db.Exec(`INSERT INTO feed_sources (id, name, feed_type, url, schedule, active, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)`,
		f.ID, f.Name, f.FeedType, f.URL, f.Schedule, f.Active, f.CreatedAt)
	return err
}

func (db *DB) ListFeeds() ([]FeedSource, error) {
	rows, err := db.Query(`SELECT id, name, feed_type, url, schedule, active, last_fetched, created_at
		FROM feed_sources ORDER BY created_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []FeedSource
	for rows.Next() {
		var f FeedSource
		if err := rows.Scan(&f.ID, &f.Name, &f.FeedType, &f.URL, &f.Schedule, &f.Active,
			&f.LastFetched, &f.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, rows.Err()
}

func (db *DB) GetFeed(id string) (*FeedSource, error) {
	var f FeedSource
	err := db.QueryRow(`SELECT id, name, feed_type, url, schedule, active, last_fetched, created_at
		FROM feed_sources WHERE id = ?`, id).
		Scan(&f.ID, &f.Name, &f.FeedType, &f.URL, &f.Schedule, &f.Active, &f.LastFetched, &f.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &f, nil
}

func (db *DB) UpdateFeed(id string, name, url, schedule *string, active *int) error {
	if name != nil {
		if _, err := db.Exec(`UPDATE feed_sources SET name = ? WHERE id = ?`, *name, id); err != nil {
			return err
		}
	}
	if url != nil {
		if _, err := db.Exec(`UPDATE feed_sources SET url = ? WHERE id = ?`, *url, id); err != nil {
			return err
		}
	}
	if schedule != nil {
		if _, err := db.Exec(`UPDATE feed_sources SET schedule = ? WHERE id = ?`, *schedule, id); err != nil {
			return err
		}
	}
	if active != nil {
		if _, err := db.Exec(`UPDATE feed_sources SET active = ? WHERE id = ?`, *active, id); err != nil {
			return err
		}
	}
	return nil
}

func (db *DB) UpdateFeedLastFetched(id string) error {
	_, err := db.Exec(`UPDATE feed_sources SET last_fetched = ? WHERE id = ?`, Now(), id)
	return err
}

func (db *DB) DeleteFeed(id string) error {
	_, err := db.Exec(`DELETE FROM feed_sources WHERE id = ?`, id)
	return err
}
