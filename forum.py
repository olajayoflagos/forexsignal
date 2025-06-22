from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
import firestore_config
from firebase_admin import firestore
import os, uuid, datetime, requests

forum = Blueprint('forum', __name__)

@forum.route('/forum')
@login_required
def forum_list():
    # Fetch all posts ordered by creation time
    docs = firestore_config.db.collection('posts') \
             .order_by('created', direction=firestore.Query.DESCENDING) \
             .stream()
    posts = [p.to_dict() for p in docs]
    return render_template('forum_list.html', posts=posts)

@forum.route('/forum/post/<post_id>')
@login_required
def view_post(post_id):
    # Fetch single post and its comments
    doc = firestore_config.db.collection('posts').document(post_id).get()
    if not doc.exists:
        flash('Post not found.', 'warning')
        return redirect(url_for('forum.forum_list'))
    post = doc.to_dict()
    return render_template('post.html', post=post)

@forum.route('/forum/post', methods=['POST'])
@login_required
def new_post():
    text = request.form.get('text', '').strip()
    img = request.files.get('image')
    img_url = None
    if img and img.filename:
        # Upload to imgbb
        resp = requests.post(
            'https://api.imgbb.com/1/upload',
            data={'key': os.getenv('IMGBB_KEY')},
            files={'image': img.read()}
        )
        data = resp.json().get('data', {})
        img_url = data.get('url')
    post_id = str(uuid.uuid4())
    firestore_config.db.collection('posts').document(post_id).set({
        'id':         post_id,
        'author':     current_user.id,
        'text':       text,
        'image':      img_url,
        'created':    datetime.datetime.utcnow(),
        'comments':   []
    })
    return redirect(url_for('forum.forum_list'))

@forum.route('/forum/comment/<post_id>', methods=['POST'])
@login_required
def new_comment(post_id):
    text = request.form.get('text', '').strip()
    comment = {
        'id':      str(uuid.uuid4()),
        'by':      current_user.id,
        'text':    text,
        'created': datetime.datetime.utcnow()
    }
    firestore_config.db.collection('posts').document(post_id).update({
        'comments': firestore.ArrayUnion([comment])
    })
    return redirect(url_for('forum.view_post', post_id=post_id))
