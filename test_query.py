from app.db.mysql import db_connect; print(list(db_connect().execute('SELECT * FROM evaluation_jobs LIMIT 10').fetchall()))
