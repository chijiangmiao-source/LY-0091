import falcon


class CORSMiddleware:
    async def process_response_async(self, req, resp, resource, req_succeeded):
        resp.set_header("Access-Control-Allow-Origin", "*")
        resp.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
        resp.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        resp.set_header("Access-Control-Allow-Credentials", "true")

    async def process_request_async(self, req, resp):
        if req.method == "OPTIONS":
            resp.status = falcon.HTTP_200
            resp.complete = True
