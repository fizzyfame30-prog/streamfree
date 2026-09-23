import os
import sqlite3
from pathlib import Path
from functools import wraps
from uuid import uuid4

from flask import (
    Flask, request, redirect, url_for, session,
    g, abort, send_from_directory, render_template_string, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

BASE = Path(__file__).parent
DB_PATH = BASE / os.getenv("DATABASE_PATH", "streamfree.db")
UPLOADS = BASE / "uploads"
THUMBS = BASE / "thumbs"

VIDEO_TYPES = {".mp4", ".webm", ".mov", ".mkv"}

UPLOADS.mkdir(exist_ok=True)
THUMBS.mkdir(exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    database = g.pop("db", None)
    if database:
        database.close()


def init_db():
    db = get_db()

    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            bio TEXT DEFAULT '',
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'general',
            filename TEXT NOT NULL,
            thumbnail TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            views INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS likes (
            user_id INTEGER NOT NULL,
            video_id INTEGER NOT NULL,
            PRIMARY KEY(user_id, video_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(video_id) REFERENCES videos(id)
        );

        CREATE TABLE IF NOT EXISTS follows (
            follower_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            PRIMARY KEY(follower_id, creator_id),
            FOREIGN KEY(follower_id) REFERENCES users(id),
            FOREIGN KEY(creator_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            video_id INTEGER NOT NULL,
            parent_id INTEGER,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(video_id) REFERENCES videos(id)
        );
    """)

    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_password = os.getenv("ADMIN_PASSWORD", "change-this-password")

    exists = db.execute(
        "SELECT id FROM users WHERE email = ?", (admin_email,)
    ).fetchone()

    if not exists:
        db.execute("""
            INSERT INTO users
            (username, email, password_hash, bio, is_admin)
            VALUES (?, ?, ?, ?, 1)
        """, (
            "admin",
            admin_email,
            generate_password_hash(admin_password),
            "Platform administrator",
        ))

    db.commit()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    return get_db().execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            return "Admin access required.", 403
        return function(*args, **kwargs)
    return wrapper


def make_thumbnail(title, category):
    filename = f"{uuid4().hex}.svg"
    safe_title = title[:30].replace("&", "and")

    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">
        <defs>
            <linearGradient id="g" x1="0" x2="1">
                <stop stop-color="#2563eb"/>
                <stop offset="1" stop-color="#9333ea"/>
            </linearGradient>
        </defs>
        <rect width="1280" height="720" fill="url(#g)"/>
        <polygon points="560,260 560,460 760,360" fill="white"/>
        <text x="640" y="550"
              text-anchor="middle"
              fill="white"
              font-size="42"
              font-family="Arial">{safe_title}</text>
        <text x="640" y="610"
              text-anchor="middle"
              fill="#e2e8f0"
              font-size="24"
              font-family="Arial">{category.upper()}</text>
    </svg>
    """

    (THUMBS / filename).write_text(svg, encoding="utf-8")
    return filename


def page(title, content):
    user = current_user()

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>{{ title }} - StreamFree</title>
        <style>
            * { box-sizing: border-box; }
            body {
                margin: 0;
                background: #0f172a;
                color: #f8fafc;
                font-family: Arial, sans-serif;
            }
            nav {
                background: #111827;
                padding: 18px;
                display: flex;
                justify-content: space-between;
                gap: 15px;
                flex-wrap: wrap;
            }
            nav a, a { color: #93c5fd; text-decoration: none; }
            .container {
                max-width: 1150px;
                margin: 30px auto;
                padding: 0 18px 50px;
            }
            .card, .panel {
                background: #1e293b;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 14px;
            }
            .grid {
                display: grid;
                grid-template-columns:
                    repeat(auto-fit, minmax(270px, 1fr));
                gap: 20px;
            }
            .thumbnail {
                width: 100%;
                height: 180px;
                object-fit: cover;
                border-radius: 10px;
            }
            video {
                width: 100%;
                max-height: 650px;
                background: black;
                border-radius: 12px;
            }
            input, textarea, select, button {
                width: 100%;
                padding: 12px;
                margin: 7px 0;
                border-radius: 8px;
                border: 1px solid #475569;
                background: #0f172a;
                color: white;
            }
            button, .button {
                background: #2563eb;
                border: 0;
                color: white;
                cursor: pointer;
                display: inline-block;
                padding: 11px 15px;
                border-radius: 8px;
            }
            .danger { background: #dc2626; }
            .muted { color: #94a3b8; }
            .comment {
                border-top: 1px solid #475569;
                padding: 14px 0;
            }
            .reply {
                margin-left: 25px;
                padding: 10px;
                background: #0f172a;
                border-radius: 8px;
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 15px;
            }
            .stat {
                background: #111827;
                padding: 18px;
                border-radius: 10px;
                text-align: center;
            }
            @media(max-width:700px) {
                .stats { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <nav>
            <strong>StreamFree</strong>
            <div>
                <a href="/">Home</a> |
                <a href="/trending">Trending</a> |
                {% if user %}
                    <a href="/dashboard">Dashboard</a> |
                    <a href="/upload">Upload</a> |
                    {% if user["is_admin"] %}
                        <a href="/admin">Admin</a> |
                    {% endif %}
                    <a href="/logout">Logout</a>
                {% else %}
                    <a href="/login">Login</a> |
                    <a href="/register">Register</a>
                {% endif %}
            </div>
        </nav>

        <main class="container">
            {% with messages = get_flashed_messages() %}
                {% for message in messages %}
                    <div class="panel">{{ message }}</div>
                {% endfor %}
            {% endwith %}

            {{ content|safe }}
        </main>
    </body>
    </html>
    """, title=title, content=content, user=user)


@app.route("/")
def home():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    query = """
        SELECT v.*, u.username,
        (SELECT COUNT(*) FROM likes WHERE video_id = v.id) AS likes
        FROM videos v
        JOIN users u ON u.id = v.user_id
        WHERE v.status = 'approved'
    """
    values = []

    if q:
        query += """
            AND (LOWER(v.title) LIKE LOWER(?)
            OR LOWER(v.description) LIKE LOWER(?))
        """
        values += [f"%{q}%", f"%{q}%"]

    if category and category != "all":
        query += " AND v.category = ?"
        values.append(category)

    query += " ORDER BY v.created_at DESC"

    videos = get_db().execute(query, values).fetchall()

    html = """
    <h1>Discover videos</h1>

    <form method="get">
        <input name="q" placeholder="Search videos" value="{{ q }}">
        <select name="category">
            <option value="all">All categories</option>
            {% for item in categories %}
                <option value="{{ item }}">{{ item|capitalize }}</option>
            {% endfor %}
        </select>
        <button type="submit">Search</button>
    </form>

    <div class="grid">
        {% for video in videos %}
        <div class="card">
            <img class="thumbnail"
                 src="/thumbs/{{ video['thumbnail'] }}">
            <h3>
                <a href="/watch/{{ video['id'] }}">
                    {{ video['title'] }}
                </a>
            </h3>
            <p class="muted">
                By {{ video['username'] }} |
                {{ video['views'] }} views |
                {{ video['likes'] }} likes
            </p>
            <p>{{ video['description'][:120] }}</p>
            <a class="button" href="/watch/{{ video['id'] }}">Watch</a>
        </div>
        {% else %}
            <div class="card">No videos found.</div>
        {% endfor %}
    </div>
    """

    return page("Home", render_template_string(
        html,
        videos=videos,
        q=q,
        categories=[
            "music", "gaming", "news", "tech",
            "education", "sports", "entertainment"
        ],
    ))


@app.route("/trending")
def trending():
    videos = get_db().execute("""
        SELECT v.*, u.username,
        (SELECT COUNT(*) FROM likes WHERE video_id = v.id) AS likes
        FROM videos v
        JOIN users u ON u.id = v.user_id
        WHERE v.status = 'approved'
        ORDER BY (v.views + likes * 10) DESC
        LIMIT 30
    """).fetchall()

    html = """
    <h1>Trending videos</h1>
    <div class="grid">
        {% for video in videos %}
        <div class="card">
            <img class="thumbnail"
                 src="/thumbs/{{ video['thumbnail'] }}">
            <h3>
                <a href="/watch/{{ video['id'] }}">
                    {{ video['title'] }}
                </a>
            </h3>
            <p>By {{ video['username'] }}</p>
            <p>{{ video['views'] }} views</p>
        </div>
        {% else %}
            <div class="card">No trending videos yet.</div>
        {% endfor %}
    </div>
    """

    return page("Trending", render_template_string(html, videos=videos))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if len(username) < 3:
            flash("Username must be at least 3 characters.")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.")
        elif "@" not in email:
            flash("Enter a valid email.")
        else:
            try:
                db = get_db()
                db.execute("""
                    INSERT INTO users
                    (username, email, password_hash)
                    VALUES (?, ?, ?)
                """, (
                    username,
                    email,
                    generate_password_hash(password),
                ))
                db.commit()
                flash("Registration successful. Please log in.")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Username or email already exists.")

    html = """
    <div class="panel">
        <h1>Create account</h1>
        <form method="post">
            <input name="username" placeholder="Username" required>
            <input name="email" type="email" placeholder="Email" required>
            <input name="password" type="password"
                   placeholder="Password" required>
            <button type="submit">Register</button>
        </form>
    </div>
    """

    return page("Register", render_template_string(html))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()

        if user and check_password_hash(
            user["password_hash"], password
        ):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    html = """
    <div class="panel">
        <h1>Login</h1>
        <form method="post">
            <input name="email" type="email" placeholder="Email" required>
            <input name="password" type="password"
                   placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
    </div>
    """

    return page("Login", render_template_string(html))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "general")
        video = request.files.get("video")

        if not title or not video or not video.filename:
            flash("Title and video are required.")
            return redirect(url_for("upload"))

        extension = Path(video.filename).suffix.lower()

        if extension not in VIDEO_TYPES:
            flash("Unsupported video format.")
            return redirect(url_for("upload"))

        filename = f"{uuid4().hex}{extension}"
        video.save(UPLOADS / filename)

        thumbnail = make_thumbnail(title, category)

        get_db().execute("""
            INSERT INTO videos
            (user_id, title, description, category, filename, thumbnail)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            session["user_id"],
            title,
            description,
            category,
            filename,
            thumbnail,
        ))
        get_db().commit()

        flash("Video uploaded and waiting for admin approval.")
        return redirect(url_for("dashboard"))

    html = """
    <div class="panel">
        <h1>Upload video</h1>
        <form method="post" enctype="multipart/form-data">
            <input name="title" placeholder="Video title" required>
            <textarea name="description"
                      placeholder="Description"></textarea>

            <select name="category">
                <option value="general">General</option>
                <option value="music">Music</option>
                <option value="gaming">Gaming</option>
                <option value="news">News</option>
                <option value="tech">Tech</option>
                <option value="education">Education</option>
                <option value="sports">Sports</option>
                <option value="entertainment">Entertainment</option>
            </select>

            <input name="video"
                   type="file"
                   accept=".mp4,.webm,.mov,.mkv"
                   required>

            <button type="submit">Upload</button>
        </form>
    </div>
    """

    return page("Upload", render_template_string(html))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()

    videos = get_db().execute("""
        SELECT *
        FROM videos
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user["id"],)).fetchall()

    views = sum(video["views"] for video in videos)
    followers = get_db().execute(
        "SELECT COUNT(*) AS total FROM follows WHERE creator_id = ?",
        (user["id"],)
    ).fetchone()["total"]

    html = """
    <h1>Dashboard</h1>

    <div class="stats">
        <div class="stat">
            <strong>{{ videos|length }}</strong>
            <span>Uploads</span>
        </div>
        <div class="stat">
            <strong>{{ views }}</strong>
            <span>Views</span>
        </div>
        <div class="stat">
            <strong>{{ followers }}</strong>
            <span>Followers</span>
        </div>
    </div>

    <p>
        <a class="button" href="/upload">Upload video</a>
    </p>

    <div class="panel">
        <h2>Your videos</h2>
        {% for video in videos %}
            <p>
                <a href="/watch/{{ video['id'] }}">
                    {{ video['title'] }}
                </a>
                — {{ video['status'] }} —
                {{ video['views'] }} views
            </p>
        {% else %}
            <p>You have not uploaded any videos.</p>
        {% endfor %}
    </div>
    """

    return page("Dashboard", render_template_string(
        html,
        user=user,
        videos=videos,
        views=views,
        followers=followers,
    ))


@app.route("/watch/<int:video_id>", methods=["GET", "POST"])
def watch(video_id):
    db = get_db()

    video = db.execute("""
        SELECT v.*, u.username, u.bio
        FROM videos v
        JOIN users u ON u.id = v.user_id
        WHERE v.id = ?
    """, (video_id,)).fetchone()

    if not video:
        abort(404)

    if video["status"] != "approved":
        user = current_user()
        if not user or user["id"] != video["user_id"]:
            abort(404)

    if request.method == "POST":
        user = current_user()

        if not user:
            return redirect(url_for("login"))

        content = request.form.get("content", "").strip()
        parent_id = request.form.get("parent_id", type=int)

        if content:
            db.execute("""
                INSERT INTO comments
                (user_id, video_id, parent_id, content)
                VALUES (?, ?, ?, ?)
            """, (
                user["id"],
                video_id,
                parent_id,
                content,
            ))
            db.commit()

        return redirect(url_for("watch", video_id=video_id))

    db.execute(
        "UPDATE videos SET views = views + 1 WHERE id = ?",
        (video_id,)
    )
    db.commit()

    comments = db.execute("""
        SELECT c.*, u.username
        FROM comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.video_id = ?
        ORDER BY c.created_at ASC
    """, (video_id,)).fetchall()

    liked = False
    following = False
    user = current_user()

    if user:
        liked = bool(db.execute("""
            SELECT 1 FROM likes
            WHERE user_id = ? AND video_id = ?
        """, (user["id"], video_id)).fetchone())

        following = bool(db.execute("""
            SELECT 1 FROM follows
            WHERE follower_id = ? AND creator_id = ?
        """, (user["id"], video["user_id"])).fetchone())

    html = """
    <div class="panel">
        <h1>{{ video['title'] }}</h1>
        <p class="muted">
            By {{ video['username'] }} |
            {{ video['views'] }} views |
            {{ video['category'] }}
        </p>

        <video controls autoplay>
            <source src="/videos/{{ video['filename'] }}">
        </video>

        <p>{{ video['description'] }}</p>

        {% if user %}
            <form method="post" action="/like/{{ video['id'] }}">
                <button type="submit">
                    {% if liked %}Unlike{% else %}Like{% endif %}
                </button>
            </form>

            <form method="post"
                  action="/follow/{{ video['user_id'] }}">
                <button type="submit">
                    {% if following %}Unfollow{% else %}Follow creator{% endif %}
                </button>
            </form>
        {% endif %}
    </div>

    <div class="panel">
        <h2>Comments</h2>

        {% if user %}
            <form method="post">
                <textarea name="content"
                          placeholder="Write a comment..."
                          required></textarea>
                <button type="submit">Comment</button>
            </form>
        {% endif %}

        {% for comment in comments if not comment['parent_id'] %}
            <div class="comment">
                <strong>{{ comment['username'] }}</strong>
                <p>{{ comment['content'] }}</p>

                {% if user %}
                    <form method="post">
                        <input type="hidden"
                               name="parent_id"
                               value="{{ comment['id'] }}">
                        <input name="content"
                               placeholder="Reply..."
                               required>
                        <button type="submit">Reply</button>
                    </form>
                {% endif %}

                {% for reply in comments
                    if reply['parent_id'] == comment['id'] %}
                    <div class="reply">
                        <strong>{{ reply['username'] }}</strong>
                        <p>{{ reply['content'] }}</p>
                    </div>
                {% endfor %}
            </div>
        {% else %}
            <p>No comments yet.</p>
        {% endfor %}
    </div>
    """

    return page("Watch", render_template_string(
        html,
        video=video,
        comments=comments,
        user=user,
        liked=liked,
        following=following,
    ))


@app.post("/like/<int:video_id>")
@login_required
def like(video_id):
    db = get_db()
    user_id = session["user_id"]

    existing = db.execute("""
        SELECT 1 FROM likes
        WHERE user_id = ? AND video_id = ?
    """, (user_id, video_id)).fetchone()

    if existing:
        db.execute("""
            DELETE FROM likes
            WHERE user_id = ? AND video_id = ?
        """, (user_id, video_id))
    else:
        db.execute("""
            INSERT INTO likes (user_id, video_id)
            VALUES (?, ?)
        """, (user_id, video_id))

    db.commit()
    return redirect(url_for("watch", video_id=video_id))


@app.post("/follow/<int:creator_id>")
@login_required
def follow(creator_id):
    db = get_db()
    user_id = session["user_id"]

    if user_id == creator_id:
        abort(400)

    existing = db.execute("""
        SELECT 1 FROM follows
        WHERE follower_id = ? AND creator_id = ?
    """, (user_id, creator_id)).fetchone()

    if existing:
        db.execute("""
            DELETE FROM follows
            WHERE follower_id = ? AND creator_id = ?
        """, (user_id, creator_id))
    else:
        db.execute("""
            INSERT INTO follows (follower_id, creator_id)
            VALUES (?, ?)
        """, (user_id, creator_id))

    db.commit()
    return redirect(request.referrer or url_for("home"))


@app.route("/profile/<username>")
def profile(username):
    db = get_db()

    creator = db.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()

    if not creator:
        abort(404)

    videos = db.execute("""
        SELECT *
        FROM videos
        WHERE user_id = ? AND status = 'approved'
        ORDER BY created_at DESC
    """, (creator["id"],)).fetchall()

    followers = db.execute(
        "SELECT COUNT(*) AS total FROM follows WHERE creator_id = ?",
        (creator["id"],)
    ).fetchone()["total"]

    html = """
    <div class="panel">
        <h1>{{ creator['username'] }}</h1>
        <p>{{ creator['bio'] or 'No bio yet.' }}</p>
        <p>{{ followers }} followers</p>
    </div>

    <div class="grid">
        {% for video in videos %}
        <div class="card">
            <img class="thumbnail"
                 src="/thumbs/{{ video['thumbnail'] }}">
            <h3>
                <a href="/watch/{{ video['id'] }}">
                    {{ video['title'] }}
                </a>
            </h3>
            <p>{{ video['views'] }} views</p>
        </div>
        {% else %}
            <div class="card">No public videos.</div>
        {% endfor %}
    </div>
    """

    return page("Profile", render_template_string(
        html,
        creator=creator,
        videos=videos,
        followers=followers,
    ))


@app.route("/admin")
@admin_required
def admin():
    videos = get_db().execute("""
        SELECT v.*, u.username
        FROM videos v
        JOIN users u ON u.id = v.user_id
        WHERE v.status = 'pending'
        ORDER BY v.created_at ASC
    """).fetchall()

    html = """
    <h1>Admin moderation</h1>

    {% for video in videos %}
    <div class="panel">
        <h3>{{ video['title'] }}</h3>
        <p>Uploaded by {{ video['username'] }}</p>

        <form method="post"
              action="/admin/{{ video['id'] }}/approve">
            <button type="submit">Approve</button>
        </form>

        <form method="post"
              action="/admin/{{ video['id'] }}/reject">
            <button class="danger" type="submit">Reject</button>
        </form>
    </div>
    {% else %}
        <p>No pending videos.</p>
    {% endfor %}
    """

    return page("Admin", render_template_string(html, videos=videos))


@app.post("/admin/<int:video_id>/<action>")
@admin_required
def moderate(video_id, action):
    if action not in ("approve", "reject"):
        abort(400)

    status = "approved" if action == "approve" else "rejected"

    get_db().execute(
        "UPDATE videos SET status = ? WHERE id = ?",
        (status, video_id)
    )
    get_db().commit()

    return redirect(url_for("admin"))


@app.route("/videos/<path:filename>")
def serve_video(filename):
    return send_from_directory(UPLOADS, filename)


@app.route("/thumbs/<path:filename>")
def serve_thumb(filename):
    return send_from_directory(THUMBS, filename)


if __name__ == "__main__":
    with app.app_context():
        init_db()

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
