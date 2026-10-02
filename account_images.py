"""Content-addressed avatar thumbnails; original account images stay untouched."""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import warnings

_lock=threading.Lock()


def avatar_url(value):
    if isinstance(value,str) and value.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):
        return '/avatars/'+hashlib.sha256(value.encode()).hexdigest()+'.webp'
    return value


def public_avatars(value):
    if isinstance(value,list):return [public_avatars(item) for item in value]
    if isinstance(value,dict):return {key:(avatar_url(item) if key in {'avatar','avatarUrl','discord_avatar'} else public_avatars(item)) for key,item in value.items()}
    return value


def thumbnail(key, accounts_path, output_dir, club_path=None):
    if not re.fullmatch(r'[a-f0-9]{64}',key):return None
    output=Path(output_dir)/'avatar-thumbnails';target=output/(key+'.webp')
    if target.is_file():return target
    with _lock:
        if target.is_file():return target
        import registered_names
        data=registered_names.read_accounts(accounts_path)
        candidates=[account.get(field,'') for account in data.get('users',{}).values() for field in ('avatar','discord_avatar')]
        def matching(values):
            return next((value for value in values if isinstance(value,str) and value.startswith('data:image/') and hashlib.sha256(value.encode()).hexdigest()==key),None)
        source=matching(candidates)
        if source is None and club_path and Path(club_path).exists():
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(Path(club_path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='competition_participants'").fetchone():
                    source=matching(row[0] for row in db.execute("SELECT DISTINCT avatar FROM competition_participants WHERE avatar LIKE 'data:image/%'"))
        if source is None or len(source)>1_500_000:return None
        from PIL import Image,ImageOps
        try:
            raw=base64.b64decode(source.split(',',1)[1],validate=True)
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width*image.height>16_000_000:return None
                    image=ImageOps.exif_transpose(image)
                    image.thumbnail((128,128))
                    output.mkdir(parents=True,exist_ok=True)
                    temporary=target.with_suffix('.tmp')
                    image.convert('RGBA' if 'A' in image.getbands() else 'RGB').save(temporary,'WEBP',quality=82)
                    temporary.replace(target)
        except (ValueError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):return None
    return target
