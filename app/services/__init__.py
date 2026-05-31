"""Service layer: business logic and data assembly one step away from routes.

Routers stay thin (parse request, hand off, return response). Anything that
joins sources, computes, or branches on business rules lives here. Modules
in this package do not import from `app.routers`."""
