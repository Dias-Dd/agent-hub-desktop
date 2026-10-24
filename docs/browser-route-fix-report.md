# Browser local route fix

Local HTML screenshot requests now separate filesystem path, query and fragment before checking the project/baseline boundary. Edge receives the preserved query and fragment. Remote URLs and paths outside the allowed roots remain rejected. Audit and return data include the actual page URL.

Validation: test_browser_routes.py: 46 passing tests (includes inherited automation fixtures), including a real headless Edge screenshot at 640x480 with query and fragment, plus directory/remote URL rejection. No model calls. Source synchronized to desktop build source. Existing running frozen desktop backend has not been restarted or replaced by this change; a rebuilt desktop executable is required for activation.
