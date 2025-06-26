import toml

def load_config(path="config.toml"):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return toml.load(f)
    except FileNotFoundError:
        print("错误：找不到 config.toml 文件！")
        exit(1)

config = load_config()