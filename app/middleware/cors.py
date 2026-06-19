import falcon


class CORSMiddleware:
    def process_response(self, req, resp, resource, req_succeeded):
        resp.set_header("Access-Control-Allow-Origin", "*")
        resp.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
        resp.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        resp.set_header("Access-Control-Allow-Credentials", "true")

    def process_request(self, req, resp):
        if req.method == "OPTIONS":
            resp.status = falcon.HTTP_200
            resp.complete = True
