"""
Interactive runner for Flow B — MSME Query Pipeline.

Usage:
    python -m scripts.run_flow_b

Lets a user type natural-language questions and sends them through the
REAL Flow B pipeline:

    Query Understanding
        -> Entity Resolution
        -> Authorization Gate
        -> Router
        -> Response Synthesis

Type "exit" or "quit" to stop.
"""

from app.query.router import route_query
from app.query.response_synthesis import synthesize_response


DEFAULT_USER_ID = "RM001"


def run_interactive_flow_b(user_id: str = DEFAULT_USER_ID) -> None:
    print("=" * 55)
    print("MSME INTERACTIVE QUERY — FLOW B")
    print("=" * 55)
    print(f"Logged in as: {user_id}")
    print('Type "exit" or "quit" to stop.')
    print()

    while True:
        try:
            question = input("Ask a question > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting Flow B.")
            break

        if not question:
            continue

        if question.lower() in {"exit", "quit"}:
            print("Exiting Flow B.")
            break

        try:
            route_result = route_query(
                user_id=user_id,
                text=question,
            )

            response = synthesize_response(route_result)

            print()
            print("Response:")
            print(response["reply"])
            print()
            print(f"Grounded in: {response['grounded_in']}")
            print("-" * 55)

        except Exception as exc:
            print()
            print(
                f"Flow B error: {type(exc).__name__}: {exc}"
            )
            print("-" * 55)


if __name__ == "__main__":
    run_interactive_flow_b()