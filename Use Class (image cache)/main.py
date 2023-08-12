import socket
import threading
import time
import configparser
import datetime
import os
import shutil


class ImageCache:
    def __init__(self, cache_timeout, cache_directory):
        self.cache_timeout = cache_timeout
        self.cache_directory = cache_directory
        self.cache_creation_time = time.time()

        if not os.path.exists(cache_directory):
            os.makedirs(cache_directory)

        if time.time() - os.path.getctime(cache_directory) >= self.cache_timeout:
            try:
                shutil.rmtree(cache_directory)
                os.makedirs(cache_directory)
                print("Cache has been cleared")
            except Exception as Error:
                print(f"Error while delete cache data: {Error}")

    def get(self, website, image_name):
        file_path = os.path.join(self.cache_directory, website, image_name)
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                return f.read()
        else:
            return None

    def put(self, website, image_name, image_data):
        website_directory = os.path.join(self.cache_directory, website)

        if not os.path.exists(website_directory):
            os.makedirs(website_directory)

        file_path = os.path.join(website_directory, image_name)
        with open(file_path, "wb") as f:
            f.write(image_data)


def parse_data(client_data):
    data = client_data.split(b"\r\n\r\n")
    lines = data[0].split(b"\r\n")

    if len(lines) < 1:
        return None, None, None
    
    method, url, _ = lines[0].split(b" ", 2)
    headers = {}
    for line in lines[1:]:
        if b":" in line:
            key, value = line.split(b":", 1)
            key = key.strip().decode("utf-8").lower()
            value = value.strip().decode("utf-8")
            headers[key] = value
    return method.decode("utf-8"), url.decode("utf-8"), headers


def read_config(filename):
    config = configparser.ConfigParser()
    try:
        config.read(filename)
        cache_time = int(config["ProxyConfig"]["cache_time"])
        whitelisting = [
            domain.strip()
            for domain in config["ProxyConfig"]["whitelisting"].split(",")
        ]
        time_range = [int(t) for t in config["ProxyConfig"]["time"].split("-")]
        return cache_time, whitelisting, time_range
    except Exception as Error:
        print(f"Error reading configuration file: {Error}")
        return None, None, None


def error_403_with_html(file_path):
    try:
        with open(file_path, "rb") as file:
            data = b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\n"
            data += file.read()
        return data
    except Exception as Error:
        print(f"Error reading HTML file: {Error}")
        return b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\n\r\nError reading HTML file"


def is_whitelisted(domain, whitelist):
    for allowed_domain in whitelist:
        if allowed_domain in domain:
            return True
    return False


def is_within_time_range(time_range):
    now = datetime.datetime.now().time()
    start_time = datetime.time(time_range[0])
    end_time = datetime.time(time_range[1])
    return start_time <= now <= end_time


def get_ip_from_domain_name(domain_name):
    try:
        return socket.gethostbyname(domain_name)
    except socket.gaierror:
        return None


def handle_client(
    toward_client_socket, toward_client_address, whitelisting, time_range, cache
):
    print(f"New connection detected: {toward_client_address}")
    VALID_METHODS = ("GET", "HEAD", "POST")
    BUFFER_SIZE = 4096
    try:
        client_data = toward_client_socket.recv(BUFFER_SIZE)
        if client_data:
            method, url, headers = parse_data(client_data)
            if (method == None or method.upper() not in VALID_METHODS
                or not is_whitelisted(url, whitelisting)
                or not is_within_time_range(time_range)
            ):
                toward_client_socket.sendall(error_403_with_html("403.html"))
                toward_client_socket.close()
                return

            image_name = url.split("/")[-1]
            domain_name = url.split("//")[-1].split("/")[0]

            if "image/" in headers.get("accept", "") and len(image_name) > 0:
                cache_image = cache.get(domain_name, image_name)

                if cache_image:
                    print("Serving from cache")
                    toward_client_socket.sendall(cache_image)
                    toward_client_socket.close()
                    return

            toward_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                SERVER_ADDRESS = (get_ip_from_domain_name(domain_name), 80)
                toward_server_socket.connect(SERVER_ADDRESS)
                print(f"Linked to: {SERVER_ADDRESS}")

                toward_server_socket.sendall(client_data)
                response_data = toward_server_socket.recv(BUFFER_SIZE)
                response_method, response_url, response_headers = parse_data(
                    response_data
                )

                if "transfer-encoding" in response_headers:
                    while not response_data.endswith(b"0\r\n\r\n"):
                        try:
                            data = toward_server_socket.recv(BUFFER_SIZE)
                            response_data += data
                        except Exception as Error:
                            print(f"Error while getting data from Server: {Error}")
                            break

                elif "content-length" in response_headers:
                    while len(response_data) < int(response_headers["content-length"]):
                        try:
                            data = toward_server_socket.recv(BUFFER_SIZE)
                            response_data += data
                        except Exception as Error:
                            print(f"Error while getting data from Server: {Error}")
                            break

                if response_headers.get("content-type", "").startswith("image/"):
                    cache.put(domain_name, image_name, response_data)
                
                print(domain_name)
                print(response_method)
                print(response_url)
                print(response_headers)
                toward_client_socket.sendall(response_data)

            except Exception as Error:
                print(f"Error while getting Server's IP: {Error}")
            finally:
                toward_server_socket.close()

    except Exception as Error:
        print(f"Error occurred with the client socket: {Error}")
    finally:
        print(f"Connection closed: {toward_client_address}")
        toward_client_socket.close()


def main():
    CACHE_TIMEOUT, WHITELISTING, TIME_RANGE = read_config("config.ini")
    if CACHE_TIMEOUT == None or WHITELISTING == None or TIME_RANGE == None:
        print("Configuration file is missing or invalid. Exiting...")
        return

    CLIENT_ADDRESS = ("localhost", 8080)
    BACKLOG = 5
    CACHE_DIRECTORY = "image_cache"
    CACHE = ImageCache(CACHE_TIMEOUT, CACHE_DIRECTORY)

    try:
        proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxy.bind(CLIENT_ADDRESS)
        proxy.listen(BACKLOG)

        print(f"Proxy is listening at: {CLIENT_ADDRESS}")
        while True:
            try:
                toward_client_socket, toward_client_address = proxy.accept()
                client_thread = threading.Thread(
                    target=handle_client,
                    args=(
                        toward_client_socket,
                        toward_client_address,
                        WHITELISTING,
                        TIME_RANGE,
                        CACHE,
                    ),
                )
                client_thread.start()
            except Exception as Error:
                print(f"Error while accepting connection: {Error}")
    except Exception as Error:
        print(f"Error during socket setup: {Error}")
    finally:
        proxy.close()


if __name__ == "__main__":
    main()