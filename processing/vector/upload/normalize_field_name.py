MAX_FIELD_LENGTH = 63


def normalize_field_name(name: str, current_names: list[str]) -> str:
    """
    カラム名の正規化
    - 先頭と末尾の空白を削除
    - 改行コードをアンダースコアに置換
    - 最大文字列長にカット
    - カット後に重複していたら連番を付与
    """
    normalized = name.strip()

    # 改行コードをアンダースコアに置換
    # Windowsの改行コードを先に処理
    normalized = normalized.replace("\r\n", "_")
    # 残りのケースを処理（1文字の場合）
    normalized = normalized.replace("\n", "_")
    normalized = normalized.replace("\r", "_")

    # 最大文字数制限
    if len(normalized) > MAX_FIELD_LENGTH:
        normalized = normalized[:MAX_FIELD_LENGTH]

    # もしすでに正規化されたカラム名と重複していたら連番を付与
    # 最大文字数が10文字だとして
    # "field123456" -> "field12345" とカットされた場合
    # "field12345" がすでに存在していたら
    # "field123_1", "field123_2", ... "field12_10", ... と連番を付与していく
    if normalized not in current_names:
        return normalized

    base_name = normalized
    suffix_num = 1
    while True:
        suffix = f"_{suffix_num}"
        # 連番を付与した際に最大文字数を超える場合、ベース名を切り詰める
        if len(base_name) + len(suffix) > MAX_FIELD_LENGTH:
            base_name = base_name[: MAX_FIELD_LENGTH - len(suffix)]
        new_name = f"{base_name}{suffix}"
        if new_name not in current_names:
            return new_name
        suffix_num += 1
