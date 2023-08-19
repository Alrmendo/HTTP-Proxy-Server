import socket, threading
import time, datetime
import configparser
import os


class ImageCache:
    # Khởi tạo cache với 2 thông số là đường dẫn và thời gian tồn tại.
    def __init__(self, cache_timeout, cache_directory):
        self.cache_timeout = cache_timeout
        self.cache_directory = cache_directory
        self.cache_lock = threading.Lock()  # Khóa đồng bộ

        # Tạo thư mục cache nếu thư mục này chưa tồn tại.
        if not os.path.exists(cache_directory):
            os.makedirs(cache_directory)

        # Bắt đầu tiến trình dọn dẹp cache.
        self.start_cache_cleanup_thread()

    # Tạo 1 luồng con (daemon), tự động kết thúc khi chương trình chính kết thúc.
    def start_cache_cleanup_thread(self):
        cache_cleanup_thread = threading.Thread(target=self.clear_expired_cache)
        cache_cleanup_thread.daemon = True
        cache_cleanup_thread.start()

    # Phương thức dùng để dọn dẹp cache.
    def clear_expired_cache(self):
        while True:
            try:
                current_time = time.time()
                with self.cache_lock:
                    for root, dirs, files in os.walk(self.cache_directory):
                        for file in files:
                            file_path = os.path.join(root, file)
                            if current_time - os.path.getctime(file_path) >= self.cache_timeout:
                                os.remove(file_path)
                                print(f"Removed expired cache file: {file_path}")
            except Exception as Error:
                print(f"Error while deleting cache data: {Error}")
            time.sleep(self.cache_timeout)

    # Phương thức dùng để lấy ra hình ảnh trong cache.
    def get(self, website, image_name):
        file_path = os.path.join(self.cache_directory, website, image_name)
        with self.cache_lock:  # Sử dụng khóa đồng bộ khi dọn dẹp cache
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    return f.read()
            else:
                return None

    # Phương thức dùng để thêm hình ảnh trong cache.
    def put(self, website, image_name, image_data):
        website_directory = os.path.join(self.cache_directory, website)

        with self.cache_lock:
            if not os.path.exists(website_directory):
                os.makedirs(website_directory)

            file_path = os.path.join(website_directory, image_name)
            with open(file_path, "wb") as f:
                f.write(image_data)


def parse_data(input_data):
    # Tách phần tiêu đề và phần nội dung.
    split_data = input_data.split(b"\r\n\r\n", 1)

    lines = split_data[0].split(b"\r\n")
    if len(lines) < 1:
        return None, None, None
    method, url, _ = lines[0].split(b" ", 2)

    # Dùng 1 từ điển để lưu các thuộc tính của phần tiêu đề.
    headers = {}
    for line in lines[1:]:
        if b":" in line:
            key, value = line.split(b":", 1)
            key = key.strip().lower().decode("utf-8")
            value = value.strip().lower().decode("utf-8")
            headers[key] = value
    return [method.decode("utf-8"), url.decode("utf-8"), headers]


def read_config(filename):
    # Đọc cấu hình của chương trình từ file config.
    config = configparser.ConfigParser()
    try:
        config.read(filename)
        cache_time = int(config["ProxyConfig"]["cache_time"])
        whitelisting = [domain.strip() for domain in config["ProxyConfig"]["whitelisting"].split(",")]
        time_range = [int(t) for t in config["ProxyConfig"]["time"].split("-")]
        return cache_time, whitelisting, time_range
    except Exception as Error:
        print(f"Error reading configuration file: {Error}")
        return None, None, None


def error_403_with_html(file_path):
    # Đọc nội dung của file HTML.
    try:
        with open(file_path, "rb") as file:
            data = b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\n"
            data += file.read()
        return data
    except Exception as Error:
        print(f"Error reading HTML file: {Error}")
        return b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\n\r\nError reading HTML file"


def is_whitelisted(domain, whitelist):
    # Kiểm tra tên miền hiện tại có nằm trong danh sách cho phép hay không?
    for allowed_domain in whitelist:
        if allowed_domain in domain:
            return True
    return False


def is_within_time_range(time_range):
    # Kiểm tra thời gian hiện tại có nằm trong khoảng được truy cập hay không?
    now = datetime.datetime.now().time()
    start_time = datetime.time(time_range[0])
    end_time = datetime.time(time_range[1])
    return start_time <= now <= end_time


def get_ip_by_domain_name(domain_name):
    # Lấy IP từ 1 tên miền.
    try:
        return socket.gethostbyname(domain_name)
    except Exception:
        return None


def handle_client(toward_client_socket, toward_client_address, whitelisting, time_range, cache):
    print(f"New connection detected: {toward_client_address}")
    valid_methods = ("GET", "HEAD", "POST")
    buffer_size = 5125

    try:
        # Nhận dữ liệu yêu cầu từ client.
        client_data_sent = b""
        while b"\r\n\r\n" not in client_data_sent:
            data = toward_client_socket.recv(buffer_size)
            client_data_sent += data

        if len(client_data_sent) > 0:
            # Xử lý yêu cầu của client.
            client_data = parse_data(client_data_sent)

            # Nếu yêu cầu vi phạm các quy tắc thì ra về lỗi 403.
            if client_data[0] == None or client_data[0].upper() not in valid_methods or not is_whitelisted(client_data[1], whitelisting) or not is_within_time_range(time_range):
                toward_client_socket.sendall(error_403_with_html("error.html"))
                return

            # Kiểm tra trong cache xem có hình ảnh cần lấy không?
            domain_name = client_data[1].split("//")[-1].split("/")[0]
            file_name = client_data[1].split("/")[-1]
            if "image/" in client_data[2].get("accept", "") and len(file_name) > 0:
                cache_image = cache.get(domain_name, file_name)
                if cache_image != None:
                    print("Loading from cache")
                    toward_client_socket.sendall(cache_image)
                    return

            # Nếu ảnh không có trong cache thì tải lại từ server.
            try:
                # Kết nối đến server.
                toward_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_address = (get_ip_by_domain_name(domain_name), 80)
                toward_server_socket.connect(server_address)
                print(f"Linked to: {domain_name}")
                toward_server_socket.sendall(client_data_sent)

                # Nhận dữ liệu trả về từ server.
                server_data_sent = b""
                while b"\r\n\r\n" not in server_data_sent:
                    data = toward_server_socket.recv(buffer_size)
                    server_data_sent += data

                # Nếu phương thức là HEAD thì trả dữ liệu nhận được về cho client và không làm gì thêm.
                if client_data[0].upper() == "HEAD":
                    toward_client_socket.sendall(server_data_sent)
                    return

                # Nếu phương thức là POST và cần xác nhận yêu cầu gửi lại thì tiếp tục gửi yêu cầu hiện tại cho Server và tiếp tục nhận dữ liệu.
                if client_data[0].upper() == "POST" and b"100" in server_data_sent.split(b"\r\n")[0]:
                    toward_server_socket.sendall(server_data_sent)
                    data = toward_server_socket.recv(buffer_size)
                    server_data_sent = data

                # Xử lý dữ liệu trả về của server.
                server_data = parse_data(server_data_sent)

                # Nếu có "transfer-encoding" trong dữ liệu trả về, nhận dữ liệu đến khi gặp b"0\r\n\r\n".
                if "transfer-encoding" in server_data[2]:
                    while not server_data_sent.endswith(b"0\r\n\r\n"):
                        try:
                            data = toward_server_socket.recv(buffer_size)
                            server_data_sent += data
                        except Exception as Error:
                            print(f"Error while getting data from Server: {Error}")
                            break

                # Nếu có "content-length" trong dữ liệu trả về, nhận dữ liệu đến khi độ dài của phần thân dữ liệu bằng content-length.
                elif "content-length" in server_data[2]:
                    while len(server_data_sent[server_data_sent.find(b"\r\n\r\n") + len(b"\r\n\r\n") :]) < int(server_data[2].get("content-length", 0)):
                        try:
                            data = toward_server_socket.recv(buffer_size)
                            server_data_sent += data
                        except Exception as Error:
                            print(f"Error while getting data from Server: {Error}")
                            break

                # Nếu nội dung trả về là loại hình ảnh thì thêm vào cache.
                if server_data[2].get("content-type", "").startswith("image/"):
                    cache.put(domain_name, file_name, server_data_sent)

                # Trả về cho client tất cả dữ liệu nhận được từ server.
                toward_client_socket.sendall(server_data_sent)
            except Exception as Error:
                print(f"Error while getting the IP of {domain_name}: {Error}")
            finally:
                toward_server_socket.close()

    except Exception as Error:
        print(f"Error occurred with the client socket: {Error}")
    finally:
        print(f"Connection closed: {toward_client_address}")
        toward_client_socket.close()


def main():
    # Khai báo các biến cần dùng trong chương trình.
    cache_timeout, whitelisting, time_range = read_config("config.ini")
    if cache_timeout == None or whitelisting == None or time_range == None:
        print("Configuration file is missing or invalid. Exiting...")
        return

    listen_address = ("127.0.0.1", 8080)
    backlog = 5
    cache_directory = "cache"
    cache = ImageCache(cache_timeout, cache_directory)

    # Khởi tạo proxy.
    try:
        proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxy.bind(listen_address)
        proxy.listen(backlog)
        print(f"Proxy is listening at: {listen_address}")

        # Cho proxy lắng nghe đến khi thoát chương trình.
        while True:
            try:
                # Chấp nhận kết nối từ client để bắt đầu xử lý yêu cầu.
                toward_client_socket, toward_client_address = proxy.accept()
                client_thread = threading.Thread(target=handle_client, args=(toward_client_socket, toward_client_address, whitelisting, time_range, cache))
                client_thread.start()
            except Exception as Error:
                print(f"Error while accepting connection: {Error}")
    except Exception as Error:
        print(f"Error during socket setup: {Error}")
    finally:
        proxy.close()


if __name__ == "__main__":
    main()
