from think_tank.graph import build_think_tank_graph


def main() -> None:
    """Run the Think Tank multi-agent deliberation system."""
    graph = build_think_tank_graph()
    print("Think Tank graph compiled successfully.")
    print(f"Graph type: {type(graph).__name__}")


if __name__ == "__main__":
    main()
