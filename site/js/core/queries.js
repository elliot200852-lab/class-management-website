/* 由 scripts/build_indexes.py 從 templates/queries.json 產生 —— 不要手改。
   前端 Store.query／watch／count 只准用這裡的查詢名（docs/ARCHITECTURE.md §2.4）。
   新增查詢：改 templates/queries.json → python3 scripts/build_indexes.py。 */
(function (g) {
  var C = g.CMW = g.CMW || {};
  C.QUERIES = {
    "albums.list": {"batch": "v1", "limit": 200, "path": "albums", "sortClient": [["order", "asc"], ["date", "desc"]], "where": [["visible", "==", true]], "who": ["reader"]},
    "albums.list.teacher": {"batch": "v1", "limit": 200, "path": "albums", "sortClient": [["order", "asc"], ["date", "desc"]], "who": ["teacher"]},
    "allowlist.all": {"batch": "v1", "limit": 500, "path": "allowlist", "who": ["teacher"]},
    "blogComments.count": {"batch": "v1", "count": true, "path": "{entry}/blog_comments", "where": [["status", "==", "visible"]], "who": ["seatParent", "teacher"]},
    "blogComments.recentParent": {"batch": "v1", "group": "blog_comments", "limit": 200, "orderBy": [["createdAt", "desc"]], "where": [["role", "==", "parent"]], "who": ["teacher"]},
    "blogComments.thread": {"batch": "v1", "limit": 200, "path": "{entry}/blog_comments", "sortClient": [["createdAt", "asc"]], "where": [["status", "==", "visible"]], "who": ["seatParent"]},
    "blogComments.thread.teacher": {"batch": "v1", "limit": 200, "path": "{entry}/blog_comments", "sortClient": [["createdAt", "asc"]], "who": ["teacher"]},
    "blogs.all": {"batch": "v1", "limit": 40, "path": "student_blogs", "sortClient": [["seat", "asc"]], "who": ["teacher"]},
    "comments.admin": {"batch": "v1", "cursor": "startAfter", "group": "comments", "limit": 200, "orderBy": [["createdAt", "desc"]], "watch": true, "who": ["teacher"]},
    "comments.count": {"batch": "v1", "count": true, "path": "{thread}/comments", "where": [["status", "==", "visible"]], "who": ["reader", "privateReader", "teacher"]},
    "comments.thread": {"batch": "v1", "limit": 100, "orderBy": [["createdAt", "desc"]], "path": "{thread}/comments", "watch": true, "where": [["status", "==", "visible"]], "who": ["reader", "privateReader"]},
    "comments.thread.teacher": {"batch": "v1", "limit": 100, "orderBy": [["createdAt", "desc"]], "path": "{thread}/comments", "watch": true, "who": ["teacher"]},
    "entries.bySeat": {"batch": "v1", "limit": 300, "path": "student_blogs/{seat}/entries", "sortClient": [["date", "desc"], ["createdAt", "desc"]], "where": [["visible", "==", true]], "who": ["seatReader"]},
    "entries.bySeat.teacher": {"batch": "v1", "limit": 300, "path": "student_blogs/{seat}/entries", "sortClient": [["date", "desc"], ["createdAt", "desc"]], "who": ["teacher"]},
    "entries.recentParent": {"batch": "v1", "group": "entries", "limit": 100, "orderBy": [["createdAt", "desc"]], "where": [["author", "==", "parent"]], "who": ["teacher"]},
    "notifyQueue.due": {"batch": "v1.1", "limit": 50, "orderBy": [["sendAfter", "asc"]], "path": "blog_notify_queue", "where": [["state", "==", "pending"], ["sendAfter", "<=", ":now"]], "who": ["functions"]},
    "pages.byKind": {"batch": "v1", "limit": 100, "path": "pages", "sortClient": [["order", "asc"]], "where": [["visible", "==", true], ["kind", "==", ":kind"]], "who": ["reader"]},
    "pages.byKind.teacher": {"batch": "v1", "limit": 100, "path": "pages", "sortClient": [["order", "asc"]], "where": [["kind", "==", ":kind"]], "who": ["teacher"]},
    "parentMap.all": {"batch": "v1", "limit": 500, "path": "parent_child_map", "who": ["teacher"]},
    "parentPhotos.all": {"batch": "v1.1", "limit": 40, "path": "parent_photo_display", "who": ["teacher"]},
    "personalPhotos.all": {"batch": "v1.1", "limit": 40, "path": "personal_photos", "who": ["teacher"]},
    "photos.thumbs": {"batch": "v1", "cursor": "startAfter", "limit": 60, "orderBy": [["order", "asc"]], "path": "{owner}/thumbs", "who": ["reader", "privateReader", "seatReader", "teacher"]},
    "posts.byCategory": {"batch": "v1", "cursor": "startAfter", "limit": 20, "orderBy": [["date", "desc"]], "path": "posts", "where": [["visible", "==", true], ["category", "==", ":category"]], "who": ["reader"]},
    "posts.byCategory.teacher": {"batch": "v1", "cursor": "startAfter", "limit": 20, "orderBy": [["date", "desc"]], "path": "posts", "where": [["category", "==", ":category"]], "who": ["teacher"]},
    "posts.newer": {"batch": "v1", "cursor": "endBefore", "limit": 1, "limitToLast": true, "orderBy": [["date", "desc"]], "path": "posts", "where": [["visible", "==", true]], "who": ["reader"]},
    "posts.newer.teacher": {"batch": "v1", "cursor": "endBefore", "limit": 1, "limitToLast": true, "orderBy": [["date", "desc"]], "path": "posts", "who": ["teacher"]},
    "posts.recent": {"batch": "v1", "cursor": "startAfter", "limit": 20, "orderBy": [["date", "desc"]], "path": "posts", "where": [["visible", "==", true]], "who": ["reader"]},
    "posts.recent.teacher": {"batch": "v1", "cursor": "startAfter", "limit": 20, "orderBy": [["date", "desc"]], "path": "posts", "who": ["teacher"]},
    "private.list": {"batch": "v1", "limit": 100, "path": "private_posts", "sortClient": [["date", "desc"]], "where": [["visible", "==", true]], "who": ["privateReader"]},
    "private.list.teacher": {"batch": "v1", "limit": 100, "path": "private_posts", "sortClient": [["date", "desc"]], "who": ["teacher"]},
    "privateAllowlist.all": {"batch": "v1", "limit": 500, "path": "private_allowlist", "who": ["teacher"]},
    "reads.all": {"batch": "v1", "limit": 200, "path": "{thread}/reads", "who": ["teacher"]},
    "reads.count": {"batch": "v1", "count": true, "path": "{thread}/reads", "who": ["teacher"]},
    "reads.countParents": {"batch": "v1", "count": true, "path": "{thread}/reads", "where": [["kind", "==", "parent"]], "who": ["teacher"]},
    "seating.all": {"batch": "v1.1", "limit": 100, "path": "seating", "sortClient": [["date", "desc"]], "who": ["teacher"]}
  };
})(typeof window !== 'undefined' ? window : globalThis);
