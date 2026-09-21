"""Validated raster upload using the existing persistent yakuman upload directory."""
import base64
import io
import re
import warnings
from contextlib import closing
from uuid import uuid4
from filelock import FileLock
from PIL import Image, ImageOps, UnidentifiedImageError
from competition_time import utc_now
from competition_service import dump

MAX_BYTES=2*1024*1024


def upload(service,data,actor):
    raw=data.get("data","");alt=str(data.get("alt","")).strip()
    if len(alt)>300 or not isinstance(raw,str) or len(raw)>MAX_BYTES*4//3+100:raise ValueError("image_too_large")
    match=re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\r\n]+)",raw)
    if not match:raise ValueError("invalid_image_type")
    try:
        content=base64.b64decode(match[2],validate=True)
        if len(content)>MAX_BYTES:raise ValueError("image_too_large")
        with warnings.catch_warnings():
            warnings.simplefilter("error",Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"PNG","JPEG","WEBP"} or Image.MIME.get(source.format)!=match[1]:raise ValueError("image_type_mismatch")
                if source.width*source.height>16000000 or min(source.size)<1:raise ValueError("image_dimensions_invalid")
                source.verify()
            with Image.open(io.BytesIO(content)) as source:
                image=ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as error:
        raise ValueError("invalid_image_content") from error
    key=str(uuid4()); files=[]
    service.image_dir.mkdir(parents=True,exist_ok=True)
    try:
        for width in (640,1280):
            name="competition-"+key+"-"+str(width)+".webp";target=service.image_dir/name
            thumb=image.copy();thumb.thumbnail((width,width));thumb.save(target,"WEBP",quality=84)
            files.append(name)
        with FileLock(service.lock_path),closing(service.db()) as db,db:
            db.execute("INSERT INTO competition_images VALUES(?,?,?,?,?,?)",(key,*files,alt,utc_now(),str(actor)))
            service.audit(db,None,actor,"image_uploaded",{"image":key})
            return {"image":service.image(db,key)}
    except Exception:
        for name in files:(service.image_dir/name).unlink(missing_ok=True)
        raise


def delete(service,key,actor):
    with FileLock(service.lock_path),closing(service.db()) as db,db:
        for row in db.execute("SELECT draft_json,published_json FROM competitions"):
            import json
            for raw in row:
                content=json.loads(raw)
                if key==content.get("cover") or key in content.get("images",[]):raise ValueError("image_still_referenced")
        row=db.execute("SELECT * FROM competition_images WHERE id=?",(key,)).fetchone()
        if not row:raise ValueError("image_not_found")
        # Only generated filenames inside the owned storage are eligible.
        for field in ("small_file","large_file"):
            path=(service.image_dir/row[field]).resolve()
            if path.parent!=service.image_dir or not path.name.startswith("competition-"):raise ValueError("invalid_image_path")
        db.execute("DELETE FROM competition_images WHERE id=?",(key,))
        service.audit(db,None,actor,"image_deleted",{"image":key})
        # Keep the lock until both paths are removed, so a content publish cannot
        # acquire a deleted image reference between the check and unlink.
        for field in ("small_file","large_file"):(service.image_dir/row[field]).unlink(missing_ok=True)
    return {"ok":True}
