import json
import os
import random
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
DB_PATH = ROOT / 'data.db'
PUBLIC_DIR = ROOT / 'public'
PORT = 3000
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY')

WORD_BANK = [
    'algorithm', 'array', 'binary', 'compiler', 'complexity', 'concurrency',
    'data', 'database', 'debugging', 'distributed', 'encryption', 'frontend',
    'backend', 'graph', 'hashmap', 'machine', 'learning', 'model', 'network',
    'optimization', 'python', 'javascript', 'recursion', 'runtime', 'security',
    'system', 'thread', 'tree', 'vector', 'neural', 'design', 'architecture',
    'api', 'cloud', 'devops', 'testing', 'refactor'
]



def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with get_db() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS trees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                channel TEXT NOT NULL,
                tags_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tree_id INTEGER NOT NULL,
                parent_node_id INTEGER,
                video_id INTEGER NOT NULL,
                decision TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS feedback_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL,
                point_text TEXT NOT NULL,
                liked INTEGER NOT NULL
            );
        ''')
        count = db.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
        if count == 0:
            db.executemany(
                'INSERT INTO videos (youtube_id, title, channel, tags_json) VALUES (?, ?, ?, ?)',
                [(yid, title, ch, json.dumps(tags)) for yid, title, ch, tags in VIDEO_SEEDS]
            )


def tokenize(text):
    words = re.sub(r'[^a-z\s]', ' ', (text or '').lower()).split()
    return [w for w in words if w in WORD_BANK]


def max_active_guard(db):
    count = db.execute("SELECT COUNT(*) FROM trees WHERE status='active'").fetchone()[0]
    if count >= 10:
        raise ValueError('You already have 10 active trees. Archive or delete one first.')


def tree_term_scores(db, tree_id):
    scores = {w: 0 for w in WORD_BANK}
    rows = db.execute('''
        SELECT n.decision, v.tags_json, fp.point_text, fp.liked
        FROM nodes n
        JOIN videos v ON v.id = n.video_id
        LEFT JOIN feedback_points fp ON fp.node_id = n.id
        WHERE n.tree_id = ? AND n.decision IN ('liked', 'disliked')
    ''', (tree_id,)).fetchall()

    for row in rows:
        row_weight = 1 if row['decision'] == 'liked' else -1

        try:
            tags = json.loads(row['tags_json'] or '[]')
        except json.JSONDecodeError:
            tags = []

        for tag in tags:
            if tag in scores:
                scores[tag] += row_weight * 1.5

        if row['point_text']:
            point_weight = 1 if row['liked'] else -1
            for tok in tokenize(row['point_text']):
                scores[tok] += point_weight

    return scores


def choose_query_terms(db, tree_id, max_terms=3):
    scores = tree_term_scores(db, tree_id)
    
    # Sort terms by score
    positive_terms = [term for term, score in sorted(scores.items(), key=lambda x: x[1], reverse=True) if score > 0]
    negative_terms = {term for term, score in scores.items() if score < 0}
    
    # Filter out anything the user explicitly disliked
    candidates = [t for t in positive_terms if t not in negative_terms]
    
    selected = []
    # If we have learned preferences, take the best one
    if candidates:
        selected.append(candidates[0])
    
    # Fill the rest with completely random words from the bank to force new topics
    remaining_needed = max_terms - len(selected)
    random_pool = [w for w in WORD_BANK if w not in selected and w not in negative_terms]
    selected.extend(random.sample(random_pool, k=min(remaining_needed, len(random_pool))))
    
    return selected

def youtube_search(query, max_results=10):
    if not YOUTUBE_API_KEY:
        raise ValueError('Missing YOUTUBE_API_KEY environment variable')

    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'maxResults': max_results,
        'safeSearch': 'moderate',
        'videoEmbeddable': 'true',
        'key': YOUTUBE_API_KEY,
    }

    url = 'https://www.googleapis.com/youtube/v3/search?' + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={
            'Accept': 'application/json',
            'User-Agent': 'youtube-trainer/1.0'
        }
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))

    items = data.get('items', [])
    out = []

    for item in items:
        vid = item.get('id', {}).get('videoId')
        snippet = item.get('snippet', {})
        title = snippet.get('title')
        channel = snippet.get('channelTitle')

        if not vid or not title or not channel:
            continue

        tags = tokenize(f'{query} {title}')
        if not tags:
            tags = tokenize(query) or [query.lower()]

        out.append({
            'youtube_id': vid,
            'title': title,
            'channel': channel,
            'tags': tags[:6]
        })

    return out


def get_or_create_video(db, video_data):
    existing = db.execute(
        'SELECT * FROM videos WHERE youtube_id = ?',
        (video_data['youtube_id'],)
    ).fetchone()

    if existing:
        return existing

    cur = db.execute(
        'INSERT INTO videos (youtube_id, title, channel, tags_json) VALUES (?, ?, ?, ?)',
        (
            video_data['youtube_id'],
            video_data['title'],
            video_data['channel'],
            json.dumps(video_data['tags'])
        )
    )

    return db.execute('SELECT * FROM videos WHERE id = ?', (cur.lastrowid,)).fetchone()


def recommend_video_from_youtube(db, tree_id):
    # ... (keep the used_youtube_ids logic) ...

    query_terms = choose_query_terms(db, tree_id)
    # Mix up the order so YouTube doesn't give the same rank every time
    random.shuffle(query_terms) 
    query = ' '.join(query_terms)

    # Fetch more results to increase the "random" pool
    results = youtube_search(query, max_results=25) 
    fresh_results = [r for r in results if r['youtube_id'] not in used_youtube_ids]

    selected_pool = fresh_results or results
    if not selected_pool:
        raise ValueError(f'No YouTube videos found for query: {query}')

    # Pick any of the top 10 fresh results randomly
    chosen = random.choice(selected_pool[:10]) 
    return get_or_create_video(db, chosen)

def recommend_video_from_local_cache(db, tree_id):
    used = [r['video_id'] for r in db.execute('SELECT video_id FROM nodes WHERE tree_id=?', (tree_id,)).fetchall()]
    videos = db.execute('SELECT * FROM videos').fetchall()
    candidates = [v for v in videos if v['id'] not in used] or videos
    scores = tree_term_scores(db, tree_id)

    def val(video):
        try:
            tags = json.loads(video['tags_json'] or '[]')
        except json.JSONDecodeError:
            tags = []
        return sum(scores.get(t, 0) for t in tags) + random.random() * 0.3

    return sorted(candidates, key=val, reverse=True)[0]


def recommend_video(db, tree_id):
    try:
        return recommend_video_from_youtube(db, tree_id)
    except Exception as e:
        print(f'[warn] YouTube search failed, using local cache fallback: {e}')
        return recommend_video_from_local_cache(db, tree_id)


def serialize_tree(db, tree_id):
    tree = db.execute('SELECT * FROM trees WHERE id=?', (tree_id,)).fetchone()
    if not tree:
        return None

    nodes = []
    node_rows = db.execute('''
        SELECT n.*, v.youtube_id, v.title, v.channel, v.tags_json
        FROM nodes n
        JOIN videos v ON v.id = n.video_id
        WHERE n.tree_id=?
        ORDER BY n.id ASC
    ''', (tree_id,)).fetchall()

    for n in node_rows:
        points = [
            dict(r) for r in db.execute(
                'SELECT id, point_text, liked FROM feedback_points WHERE node_id=?',
                (n['id'],)
            ).fetchall()
        ]
        node = dict(n)
        node['tags'] = json.loads(node.pop('tags_json'))
        node['points'] = points
        nodes.append(node)

    out = dict(tree)
    out['nodes'] = nodes
    return out


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _read_json(self):
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length).decode() if length else '{}'
        return json.loads(raw or '{}')

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/trees':
            with get_db() as db:
                trees = [dict(r) for r in db.execute('SELECT * FROM trees ORDER BY id DESC')]
            return self._json(200, {'trees': trees})

        m = re.match(r'^/api/trees/(\d+)$', parsed.path)
        if m:
            with get_db() as db:
                tree = serialize_tree(db, int(m.group(1)))
            if not tree:
                return self._json(404, {'error': 'Tree not found'})
            return self._json(200, {'tree': tree})

        if parsed.path == '/' or parsed.path.startswith('/public') or parsed.path.endswith('.css') or parsed.path.endswith('.js') or parsed.path.endswith('.html'):
            file_path = PUBLIC_DIR / ('index.html' if parsed.path == '/' else parsed.path.lstrip('/'))
            if not file_path.exists() and parsed.path.startswith('/public/'):
                file_path = ROOT / parsed.path.lstrip('/')
            if not file_path.exists():
                self.send_response(404)
                self.end_headers()
                return

            content_type = 'text/html'
            if file_path.suffix == '.css':
                content_type = 'text/css'
            if file_path.suffix == '.js':
                content_type = 'application/javascript'

            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)

        try:
            if parsed.path == '/api/trees':
                body = self._read_json()
                with get_db() as db:
                    max_active_guard(db)
                    name = (body.get('name') or '').strip() or f"Tree {datetime.now().strftime('%H:%M:%S')}"
                    cur = db.execute("INSERT INTO trees (name, status) VALUES (?, 'active')", (name,))
                    tree_id = cur.lastrowid

                    video = recommend_video(db, tree_id)
                    db.execute(
                        'INSERT INTO nodes (tree_id, parent_node_id, video_id) VALUES (?, NULL, ?)',
                        (tree_id, video['id'])
                    )

                    tree = serialize_tree(db, tree_id)
                return self._json(201, {'tree': tree})

            m = re.match(r'^/api/trees/(\d+)/copy$', parsed.path)
            if m:
                src_id = int(m.group(1))
                with get_db() as db:
                    max_active_guard(db)
                    source = db.execute('SELECT * FROM trees WHERE id=?', (src_id,)).fetchone()
                    if not source:
                        return self._json(404, {'error': 'Tree not found'})

                    new_id = db.execute(
                        "INSERT INTO trees (name, status) VALUES (?, 'active')",
                        (f"{source['name']} (copy)",)
                    ).lastrowid

                    source_nodes = db.execute(
                        'SELECT * FROM nodes WHERE tree_id=? ORDER BY id ASC',
                        (src_id,)
                    ).fetchall()

                    node_map = {}
                    for node in source_nodes:
                        parent = node_map.get(node['parent_node_id'])
                        new_node_id = db.execute(
                            'INSERT INTO nodes (tree_id, parent_node_id, video_id, decision) VALUES (?, ?, ?, ?)',
                            (new_id, parent, node['video_id'], node['decision'])
                        ).lastrowid
                        node_map[node['id']] = new_node_id

                        pts = db.execute(
                            'SELECT point_text, liked FROM feedback_points WHERE node_id=?',
                            (node['id'],)
                        ).fetchall()

                        db.executemany(
                            'INSERT INTO feedback_points (node_id, point_text, liked) VALUES (?, ?, ?)',
                            [(new_node_id, p['point_text'], p['liked']) for p in pts]
                        )

                    tree = serialize_tree(db, new_id)
                return self._json(201, {'tree': tree})

            m = re.match(r'^/api/nodes/(\d+)/feedback$', parsed.path)
            if m:
                node_id = int(m.group(1))
                body = self._read_json()
                points = body.get('points') or []

                if body.get('decision') not in ['liked', 'disliked']:
                    return self._json(400, {'error': 'decision must be liked or disliked'})

                if len(points) < 3 or len(points) > 5:
                    return self._json(400, {'error': 'Provide 3 to 5 points'})

                with get_db() as db:
                    node = db.execute('SELECT * FROM nodes WHERE id=?', (node_id,)).fetchone()
                    if not node:
                        return self._json(404, {'error': 'Node not found'})

                    db.execute('UPDATE nodes SET decision=? WHERE id=?', (body['decision'], node_id))
                    db.execute('DELETE FROM feedback_points WHERE node_id=?', (node_id,))

                    clean = [
                        (node_id, (p.get('text') or '').strip(), 1 if p.get('liked') else 0)
                        for p in points
                        if (p.get('text') or '').strip()
                    ]

                    if len(clean) < 3:
                        return self._json(400, {'error': 'Need at least 3 non-empty points'})

                    db.executemany(
                        'INSERT INTO feedback_points (node_id, point_text, liked) VALUES (?, ?, ?)',
                        clean
                    )

                    next_video = recommend_video(db, node['tree_id'])
                    db.execute(
                        'INSERT INTO nodes (tree_id, parent_node_id, video_id) VALUES (?, ?, ?)',
                        (node['tree_id'], node_id, next_video['id'])
                    )
                    tree = serialize_tree(db, node['tree_id'])

                return self._json(200, {'tree': tree})

        except ValueError as e:
            return self._json(400, {'error': str(e)})
        except Exception as e:
            return self._json(500, {'error': str(e)})

        self.send_response(404)
        self.end_headers()

    def do_PATCH(self):
        m = re.match(r'^/api/trees/(\d+)/archive$', urlparse(self.path).path)
        if not m:
            self.send_response(404)
            self.end_headers()
            return

        tree_id = int(m.group(1))
        try:
            with get_db() as db:
                tree = db.execute('SELECT * FROM trees WHERE id=?', (tree_id,)).fetchone()
                if not tree:
                    return self._json(404, {'error': 'Tree not found'})

                status = 'active' if tree['status'] == 'archived' else 'archived'
                if status == 'active':
                    max_active_guard(db)

                db.execute('UPDATE trees SET status=? WHERE id=?', (status, tree_id))
                updated = serialize_tree(db, tree_id)

            return self._json(200, {'tree': updated})
        except ValueError as e:
            return self._json(400, {'error': str(e)})

    def do_DELETE(self):
        m = re.match(r'^/api/trees/(\d+)$', urlparse(self.path).path)
        if not m:
            self.send_response(404)
            self.end_headers()
            return

        tree_id = int(m.group(1))
        with get_db() as db:
            node_ids = [r['id'] for r in db.execute('SELECT id FROM nodes WHERE tree_id=?', (tree_id,)).fetchall()]
            db.executemany('DELETE FROM feedback_points WHERE node_id=?', [(nid,) for nid in node_ids])
            db.execute('DELETE FROM nodes WHERE tree_id=?', (tree_id,))
            db.execute('DELETE FROM trees WHERE id=?', (tree_id,))

        self.send_response(204)
        self.end_headers()


def run():
    init_db()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'Server running at http://localhost:{PORT}')
    server.serve_forever()


if __name__ == '__main__':
    run()