"""Chinese platform and action aliases for catalog discovery."""
import re

PLATFORMS = {
    'xiaohongshu-pugongying': '小红书蒲公英', 'xiaohongshu': '小红书',
    'douyin-xingtu': '抖音星图', 'douyin-shop': '抖音电商', 'douyin': '抖音',
    'wechat-channels': '微信视频号', 'wechat-mp': '微信公众号', 'wechat-search': '微信搜一搜',
    'weibo': '微博', 'bilibili': '哔哩哔哩', 'kuaishou': '快手', 'zhihu': '知乎',
    'toutiao': '今日头条', 'xigua': '西瓜视频', 'youku': '优酷', 'douban': '豆瓣',
    'taobao': '淘宝', 'jd': '京东', 'xianyu': '闲鱼', 'dewu': '得物', 'beike': '贝壳',
    'qq-huxuan': 'QQ 互选', 'pipixia': '皮皮虾', 'linkedin': '领英',
    'people': '人物', 'companies': '公司', 'creators': '达人', 'social': '社媒',
    'web': '网页', 'account': '账号', 'google': 'Google', 'github': 'GitHub',
    'youtube': 'YouTube', 'instagram': 'Instagram', 'tiktok': 'TikTok',
    'facebook': 'Facebook', 'x': 'X', 'reddit': 'Reddit',
}
ACTIONS = {
    'search': '搜索', 'profile': '主页', 'profiles': '主页', 'user': '用户', 'users': '用户',
    'creator': '达人', 'creators': '达人', 'talents': '达人', 'people': '人物',
    'posts': '帖子', 'post': '帖子', 'notes': '笔记', 'note': '笔记',
    'videos': '视频', 'video': '视频', 'comments': '评论', 'comment': '评论',
    'followers': '粉丝', 'following': '关注', 'fans_summary': '粉丝概况',
    'audience': '受众', 'insights': '洞察', 'stats': '统计', 'analytics': '分析',
    'company': '公司', 'companies': '公司', 'enrich': '信息补全', 'contact': '联系方式',
    'contacts': '联系方式', 'email': '邮箱', 'emails': '邮箱', 'find': '查找',
    'verify': '验证', 'identity': '身份', 'resolve': '关联', 'from_image': '图片来源',
    'get': '查询', 'detail': '详情', 'details': '详情', 'info': '信息', 'list': '列表',
    'channel': '频道', 'channels': '频道', 'article': '文章', 'articles': '文章',
    'live': '直播', 'likes': '点赞', 'liked_videos': '点赞视频', 'favorites': '收藏',
    'replies': '回复', 'reposts': '转发', 'related': '相关内容', 'similar': '相似内容',
    'hot': '热门', 'trending': '趋势', 'rankings': '榜单', 'hashtag': '话题',
    'hashtags': '话题', 'topic': '话题', 'topics': '话题', 'reels': '短视频',
    'subtitles': '字幕', 'transcript': '文字稿', 'download': '下载', 'images': '图片',
    'photos': '照片', 'product': '商品', 'products': '商品', 'shop': '店铺',
    'jobs': '职位', 'employees': '员工', 'repos': '代码仓库', 'repositories': '代码仓库',
    'publications': '论文', 'ads': '广告', 'keywords': '关键词', 'url': '链接',
}
ALIASES = {name: platform for platform, name in PLATFORMS.items() if re.search('[\u4e00-\u9fff]', name)}
ALIASES.update({
    '小红书达人': 'xiaohongshu creator', '公众号': 'wechat-mp', '视频号': 'wechat-channels',
    'B站': 'bilibili', 'b站': 'bilibili', '推特': 'x', '油管': 'youtube', '谷歌': 'google',
    '达人': 'creator', '博主': 'creator', '粉丝': 'followers', '评论': 'comments',
    '笔记': 'note', '帖子': 'post', '视频': 'video', '主页': 'profile', '用户': 'user',
    '搜索': 'search', '查询': 'search', '邮箱': 'email', '联系方式': 'contact',
    '文章': 'article', '直播': 'live', '公司': 'company', '招聘': 'jobs', '职位': 'jobs',
    '受众': 'audience', '话题': 'hashtag', '字幕': 'transcript', '商品': 'product',
})
_PATTERN = re.compile('|'.join(re.escape(word) for word in sorted(ALIASES, key=len, reverse=True)))


def normalize_query(query: str) -> str:
    return _PATTERN.sub(lambda match: ' ' + ALIASES[match.group()] + ' ', query)


def endpoint_label(endpoint, catalog, lang: str) -> str:
    if lang != 'zh':
        return endpoint.name or endpoint.id
    if endpoint.capability in catalog.contracts:
        return catalog.title(endpoint.capability, lang)
    platform, *parts = endpoint.capability.split('.')
    translated = [ACTIONS[part] for part in parts if part in ACTIONS]
    return PLATFORMS.get(platform, platform) + ' · ' + (' / '.join(translated) or '平台接口')
