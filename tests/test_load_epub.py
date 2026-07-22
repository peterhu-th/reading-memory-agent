from app.ingestion.load_epub import clean_book_title


def test_clean_book_title_removes_marketing_suffixes():
    assert clean_book_title("红楼梦（人文社权威定本彩皮版）") == "红楼梦"
    assert clean_book_title("心【上海译文出品】") == "心"
    assert clean_book_title("百年孤独(根据马尔克斯指定版本翻译)") == "百年孤独"
    assert clean_book_title("【精排】诗经") == "诗经"


def test_clean_book_title_keeps_real_subtitle():
    assert clean_book_title("疯癫与文明：理性时代的疯癫史") == "疯癫与文明：理性时代的疯癫史"
