def main():
    try:
        from app.ui.qt_toolbox import start as start_qt

        start_qt()
        return
    except Exception as e:
        print("Qt UI 启动失败，回退到 Tkinter UI：", repr(e))

    from app.ui.toolbox import start as start_tk

    start_tk()

if __name__ == "__main__":
    main()
