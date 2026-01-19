import json
from typing import Dict, List

from sqlalchemy import func, exists
from sqlalchemy.orm import Session

from app.core.database import session_scope
from app.models import Config, DownloadLog
from app.models.article import Article
from app.modules.downloadclient import downloadManager
from app.schemas.article import ArticleQuery
from app.schemas.response import success


def get_article_list(db: Session, query: ArticleQuery) -> Dict:
    in_stock_expr = exists().where(
        DownloadLog.tid == Article.tid
    )

    q = db.query(Article,in_stock_expr.label("in_stock"))
    if query.keyword:
        q = q.filter(Article.title.ilike(f"%{query.keyword}%"))
    if query.section:
        q = q.filter(Article.section == query.section)
    if query.sub_type:
        q = q.filter(Article.sub_type == query.sub_type)
    if query.publish_date_range:
        if query.publish_date_range['from']:
            q = q.filter(
                Article.publish_date >= query.publish_date_range['from']
            )
        if query.publish_date_range['to']:
            q = q.filter(
                Article.publish_date <= query.publish_date_range['to']
            )

    total = q.count()
    page = query.page
    per_page = query.per_page
    offset = (page - 1) * per_page

    rows = (
        q.order_by(Article.tid.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )
    items = []
    for article, in_stock in rows:
        setattr(article, "in_stock", in_stock)
        items.append(article)

    return success({
        "page": page,
        "per_page": per_page,
        "total": total,
        "items": items
    })


cn_keywords: List[str] = ['中字', '中文字幕', '色花堂', '字幕']
uc_keywords: List[str] = ['UC', '无码', '步兵']
uhd_keywords: List[str] = ['4k', '8k', '2160p', '4K', '8K', '2160P']


def has_chinese(title: str):
    chinese = False
    for keyword in cn_keywords:
        if title.find(keyword) > -1:
            chinese = True
            break
    return chinese


def has_uc(title: str):
    uc = False
    for keyword in uc_keywords:
        if title.find(keyword) > -1:
            uc = True
            break
    return uc


def has_uhd(title: str):
    uhd = False
    for keyword in uhd_keywords:
        if title.find(keyword) > -1:
            uhd = True
            break
    return uhd


def get_torrents(keyword, db: Session) -> Dict:
    articles = db.query(Article).filter(Article.title.ilike(f"%{keyword}%")).all()
    torrents = []
    for article in articles:
        torrent = {
            'id': article.tid,
            'site': 'sehuatang',
            'size_mb': article.size,
            'seeders': 66,
            'title': article.title,
            'download_url': article.magnet,
            'free': True,
            'chinese': has_chinese(f"{article.title}{article.section}"),
            'uc': has_uc(f"{article.title}{article.section}"),
            'uhd': has_uhd(f"{article.title}{article.section}")
        }
        torrents.append(torrent)
    return success(torrents)


def get_category(db: Session):
    item_count = func.count(Article.tid).label("item_count")
    result = db.query(Article.section, Article.sub_type, item_count).group_by(
        Article.section, Article.sub_type).order_by(item_count.desc()).all()
    grouped = {}

    for section, sub_type, count in result:
        if section not in grouped:
            grouped[section] = {
                "category": section,
                "count": 0,
                "items": []
            }
        if sub_type:
            grouped[section]["items"].append({
                "category": sub_type,
                "count": count
            })

        grouped[section]["count"] += count
    return success(list(grouped.values()))


def calc_score(rule, section, sub_type):
    score = 0

    if rule["category"] == section:
        score += 10
    elif rule["category"] == "ALL":
        score += 1
    else:
        return 0

    if rule["subCategory"] == sub_type:
        score += 5
    elif rule["subCategory"] == "ALL":
        score += 1
    else:
        return 0

    return score


def match_best_rules(rules, section, sub_type):
    best_score = 0
    best_rules = []

    for rule in rules:
        score = calc_score(rule, section, sub_type)
        if score == 0:
            continue

        if score > best_score:
            best_score = score
            best_rules = [rule]
        elif score == best_score:
            best_rules.append(rule)

    return best_rules


def download_magnet(tid, magnet, downloader, save_path):
    is_success = downloadManager.get(f'Downloader.{downloader}').download(magnet, save_path)
    if is_success:
        with session_scope() as db:
            download_log = DownloadLog()
            download_log.tid = tid
            download_log.magnet = magnet
            download_log.save_path = save_path
            download_log.downloader = downloader
            db.add(download_log)
    return is_success


def download_article(tid: int):
    with session_scope() as db:
        article = db.get(Article, tid)
        config = db.query(Config).filter(Config.key == 'DownloadFolder').first()
    success_count = 0
    if article and config:
        section = article.section
        sub_type = article.sub_type
        rules = json.loads(str(config.content))
        if rules:
            best_rules = match_best_rules(rules, section, sub_type)
            for rule in best_rules:
                is_success = download_magnet(article.tid, article.magnet, rule['downloader'], rule['savePath'])
                if is_success:
                    success_count += 1
    return success(f"成功添加：{success_count}")


def manul_download(tid, downloader, save_path):
    with session_scope() as db:
        article = db.get(Article, tid)
    is_success = download_magnet(article.tid, article.magnet, downloader, save_path)
    return success(is_success)
