"""Idempotent seed and deterministic leaderboard rebuild. No external messages."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from competition_service import CompetitionService, SLUG


def seed_cover(api,path):
    from competition_images import upload
    import base64
    current=api.view(SLUG,admin=True)["competition"]
    if current["cover"]:return
    image=upload(api,{"data":"data:image/jpeg;base64,"+base64.b64encode(Path(path).read_bytes()).decode(),"alt":"DORA Mahjong Club at UC San Diego"},"deployment")["image"]
    api.content(SLUG,{**current["draft"],"cover":image["key"],"version":current["version"],"publish":True,"published":True,"featured":True,"leaderboard_public":True},"deployment")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["seed","rebuild","verify"])
    parser.add_argument("--competition",default=SLUG)
    parser.add_argument("--club",required=True)
    parser.add_argument("--nfc",required=True)
    parser.add_argument("--accounts",required=True)
    parser.add_argument("--images",required=True)
    parser.add_argument("--reason",default="administrator_command")
    parser.add_argument("--cover",type=Path)
    args=parser.parse_args()
    api=CompetitionService(args.club,args.nfc,args.accounts,args.images);api.initialize()
    if args.command=="seed":
        api.seed()
        if args.cover:
            seed_cover(api,args.cover)
        api.sync()
    elif args.command=="rebuild":api.sync(rebuild=args.competition,actor="administrator_command",reason=args.reason)
    view=api.view(args.competition)
    print(json.dumps({"competition":view["competition"],"participants":view["participant_count"]},ensure_ascii=False))

if __name__=="__main__":main()
