import socket
import configparser
import datetime
import threading
import os
import shutil
import time

# Khởi tạo bộ đệm cache
class Cache:
    def __init__(self, cache_time, cache_directory):
        """
        Khởi tạo đối tượng Cache.

        Args:
            cache_time (int): Thời gian tối đa cho dữ liệu cache (tính bằng giây)
            cache_directory (str): Đường dẫn đến thư mục lưu trữ dữ liệu cache.
        """
        self.cache_time = cache_time
        self.cache_directory = cache_directory
        self.cache_creation_time = time.time()

        # Tạo thư mục cache nếu không tồn tại
        if not os.path.exists(cache_directory):
            os.makedirs(cache_directory)

        # Kiểm tra xem thời gian từ khi tạo thư mục cache đã vượt quá thời gian cache cho phép hay không
        if time.time() - os.path.getctime(cache_directory) >= self.cache_time:
            try:
                # Xóa toàn bộ dữ liệu cache và tạo lại thư mục cache
                shutil.rmtree(cache_directory)
                os.makedirs(cache_directory)
                print("Cache has been cleared")
            except Exception as Error:
                print(f"Error while deleting cache data: {Error}")

    def get(self, website, image_name):
        """
        Lấy dữ liệu cache cho trang web và tên ảnh cụ thể.

        Args:
            website (str): Tên trang web.
            image_name (str): Tên của ảnh.

        Returns:
            bytes hoặc None: Dữ liệu ảnh cache, hoặc None nếu không tìm thấy.
        """
        file_path = os.path.join(self.cache_directory, website, image_name)
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                return f.read()
        else:
            return None

    def put(self, website, image_name, image_data):
        """
        Lưu trữ dữ liệu ảnh trong cache cho trang web và tên ảnh cụ thể.

        Args:
            website (str): Tên trang web.
            image_name (str): Tên của ảnh.
            image_data (bytes): Dữ liệu ảnh cần lưu trữ trong cache.
        """
        website_directory = os.path.join(self.cache_directory, website)

        # Tạo thư mục con cho trang web nếu chưa tồn tại
        if not os.path.exists(website_directory):
            os.makedirs(website_directory)

        file_path = os.path.join(website_directory, image_name)
        with open(file_path, "wb") as f:
            f.write(image_data)

# Tải cấu hình từ config.ini
def read_Config_File(filename):
    """
    Đọc các thiết lập cấu hình từ tệp được chỉ định.
    Tham số:
        filename (str): Tên của tệp cấu hình.
    Trả về:
        tuple: Một tuple chứa các thiết lập cache_time, whitelisting, và time_range từ tệp cấu hình.
    """
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
        print(f"Error in reading config.ini file: {Error}")
        return None, None, None
    
# Kiểm tra xem một tên miền có nằm trong whitelist hay không
def is_whitelisted(domain, whitelist):
    """
    Kiểm tra xem một tên miền cụ thể có nằm trong danh sách trắng hay không.
    Tham số:
        domain (str): Tên miền cần kiểm tra.
        whitelist (list): Danh sách các tên miền trong danh sách trắng.
    Trả về:
        bool: True nếu tên miền nằm trong danh sách trắng, False nếu ngược lại.
    """
    for valid_domain in whitelist:
        if valid_domain in domain:
            return True
    return False

# Trả về nội dung HTML cho phản hồi 403 Forbidden error
def error_403_html(file_path):
    """
    Đọc và trả lại nội dung HTML cho phản hồi lỗi 403 Forbidden.
    Tham số:
        file_path (str): Đường dẫn đến tệp HTML.
    Trả về:
        bytes: Dữ liệu phản hồi lỗi.
    """
    try:
        with open(file_path, "rb") as file:
            error_data = b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\n"
            error_data += file.read()
        return error_data
    except Exception as Error:
        print(f"Error in reading HTML file: {Error}")
        return b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\n\r\nError reading HTML file"

# Phân tích dữ liệu từ máy khách để trích xuất thông tin yêu cầu HTTP
def parse_data(client_data):
    """
    Phân tích dữ liệu từ máy khách để trích xuất thông tin yêu cầu HTTP.
    Tham số:
        client_data (bytes): Dữ liệu gốc từ máy khách.
    Trả về:
        tuple: Phương thức, URL và tiêu đề đã được phân tích.
    """
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

# Lấy địa chỉ IP liên quan đến một tên miền (bỏ khúc "http://")
def get_ip_from_domain_name(domain_name):
    """
    Lấy địa chỉ IP liên quan đến một tên miền.
    Tham số:
        domain_name (str): Tên miền cần tìm địa chỉ IP.
    Trả về:
        str hoặc None: Địa chỉ IP đã tìm thấy hoặc None nếu không tìm thấy.
    """
    try:
        ip_address = socket.gethostbyname(domain_name)
        return ip_address
    except socket.gaierror:
        return None

# Kiểm tra xem thời gian hiện tại có nằm trong khoảng thời gian đã chỉ định không
def available_time_range(time_range):
    """
    Kiểm tra xem thời gian hiện tại có nằm trong khoảng thời gian đã chỉ định không.
    Tham số:
        time_range (list): Danh sách chứa thời gian bắt đầu và kết thúc.
    Trả về:
        bool: True nếu thời gian hiện tại nằm trong khoảng, False nếu ngược lại.
    """
    # lấy thời gian hiện tại
    now = datetime.datetime.now().time() # chỉ lấy thời gian
    start_time = datetime.time(time_range[0]) # thời gian bắt đầu (7h sáng)
    end_time = datetime.time(time_range[1]) # thời gian kết thúc (10h tối)
    return start_time <= now <= end_time # kiểm tra xem thời gian hiện tại có nằm giữa thời gian bắt đầu và thời gian kết thúc không

def receive_data_from_server(server):
    """
    Nhận dữ liệu từ máy chủ.

    Args:
        server (socket.socket): Đối tượng socket máy chủ.

    Returns:
        bytes: Dữ liệu nhận từ máy chủ.
    """
    data = b""
    while not data.endswith(b"\r\n\r\n"):
        try:
            chunk = server.recv(4096)
            if not chunk:
                break
            data += chunk
        except Exception as Error:
            print(f"Error while receiving data from server: {Error}")
            break
    return data

def deal_with_client(client_socket, client_address, whitelisting, time_range, cache):
    """
    Xử lý kết nối từ client và xử lý các yêu cầu HTTP.

    Args:
        client_socket (socket.socket): Đối tượng socket của client.
        client_address (tuple): Địa chỉ của client (IP, port).
        whitelisting (list): Danh sách các URL được phép.
        time_range (tuple): Tuple đại diện cho khoảng thời gian cho phép.
        cache (Cache): Đối tượng Cache để lưu trữ và truy xuất dữ liệu cache.
    """
    print(f"New connection: {client_address}")

    # Danh sách các phương thức HTTP được chấp nhận
    ACCEPT_METHOD = ("GET", "POST", "HEAD")
    try:
        # Nhận dữ liệu từ client
        client_data = client_socket.recv(4096)
        if client_data:
            # Phân tích dữ liệu nhận được từ client thành method, url và headers
            method, url, headers = parse_data(client_data)
            # Kiểm tra các điều kiện để xem liệu yêu cầu này hợp lệ không
            if method == None or method.upper() not in ACCEPT_METHOD or not is_whitelisted(url, whitelisting) or not available_time_range(time_range):
                # Gửi lỗi 403 nếu không hợp lệ
                client_socket.sendall(error_403_html("403.html"))
                client_socket.close()
                return
            
            # Trích xuất tên ảnh từ URL
            image_name = url.split("/")[-1]
            # Trích xuất tên miền từ URL
            domain_name = url.split("//")[-1].split("/")[0]
            # url.split("//"): Đoạn này sẽ tách URL thành một danh sách sử dụng chuỗi "//" như điểm tách. Ví dụ, nếu url là "https://www.example.com/page" thì kết quả sẽ là ["https:", "www.example.com/page"].
            # [-1].split("/"): Sau khi đã tách "//" từ URL, ta lấy phần tử cuối cùng của danh sách (tức là "www.example.com/page") và tiến hành tách theo dấu /. Kết quả của bước này sẽ là danh sách ["www.example.com", "page"].
            # [0]: Cuối cùng, lấy phần tử đầu tiên của danh sách sau bước tách trước đó (tức là "www.example.com") để trích xuất tên miền chính từ URL.

            # Kiểm tra xem có yêu cầu dữ liệu hình ảnh và tên ảnh có hợp lệ không
            if "image/" in headers.get("accept", "") and len(image_name) > 0:
                # Lấy dữ liệu ảnh từ cache nếu có
                cache_image = cache.get(domain_name, image_name)
                
                if cache_image:
                    print("Getting data from cache file")
                    client_socket.sendall(cache_image)
                    client_socket.close()
                    return
                
            # Tạo socket server để kết nối với máy chủ ảnh
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Lấy địa chỉ IP từ tên miền và kết nối tới máy chủ ảnh
                SERVER_ADDRESS = (get_ip_from_domain_name(domain_name), 80)
                server.connect(SERVER_ADDRESS)
                print(f"Connecting to: {domain_name}")

                # Gửi yêu cầu của client tới server ảnh
                server.sendall(client_data)
                response_data = server.recv(4096)
                response_method, response_url, response_headers = parse_data(response_data)

                if method[0].upper() == "HEAD":
                    client_socket.sendall(response_data)
                    return

                if method[0].upper() ==  "POST":
                    server.sendall(response_data)
                    response_data = receive_data_from_server(server)
                
                # Xử lý các trường hợp có "transfer-encoding" hoặc "content-length"
                if "transfer-encoding" in response_headers:
                    while not response_data.endswith(b"0\r\n\r\n"):
                        try:
                            data = server.recv(4096)
                            response_data += data
                        except Exception as Error:
                            print(f"Error while receiving data from server: {Error}")
                            break

                elif "content-length" in response_headers:
                    while len(response_data) < int(response_headers["content-length"]):
                        try:
                            data = server.recv(4096)
                            response_data += data
                        except Exception as Error:
                            print(f"Error while receiving data from server: {Error}")
                            break
                
                # Nếu đây là dữ liệu ảnh, lưu vào cache
                if response_headers.get("content-type", "").startswith("image/"):
                    cache.put(domain_name, image_name, response_data)

                print(domain_name)
                print(response_method)
                print(response_url)
                print(response_headers)
            
            except Exception as Error:
                print(f"Error while getting server's IP: {Error}")
            finally:
                server.close()
                # Gửi phản hồi từ server về cho client
                client_socket.sendall(response_data)

    except Exception as Error:
        print(f"Unable to connect to the server: {Error}")
    finally:
        print(f"Connection closed: {client_address}")
        client_socket.close()

def Proxy_Server():
    """
    Khởi chạy máy chủ Proxy để xử lý yêu cầu từ các clients.
    """
    # Đọc cấu hình từ tệp config.ini
    cache_time, whitelisting, time_range = read_Config_File("config.ini")
    if cache_time is None or whitelisting is None or time_range is None:
        # Nếu không đọc được cấu hình, thông báo và thoát khỏi hàm
        print("Can't read Configuration file. Please check if the configuration file is missing.")
        return

    CLIENT_ADDRESS = ("localhost", 8080)
    CACHE_DIRECTORY = "cache_image"
    CACHE = Cache(cache_time, CACHE_DIRECTORY)

    try:
        # Tạo socket proxy
        proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Gắn socket proxy vào địa chỉ và cổng của máy chủ
        proxy.bind(CLIENT_ADDRESS)
        # Cho phép proxy lắng nghe và xử lý tới 5 kết nối cùng một lúc
        proxy.listen(5)

        print(f"Proxy is listening at: {CLIENT_ADDRESS}")
        while True:
            try:
                # Chấp nhận kết nối từ client và tạo luồng xử lý riêng biệt
                client_socket, client_address = proxy.accept()
                client_thread = threading.Thread(target=deal_with_client, args=(client_socket, client_address, whitelisting, time_range, CACHE),)
                client_thread.start()
            except Exception as Error:
                # Nếu không thể chấp nhận kết nối, thông báo lỗi
                print(f"Connection not acceptable: {Error}")
    except Exception as Error:
        # Nếu có lỗi khi tạo socket proxy, thông báo lỗi
        print(f"Can't connect to socket: {Error}")
    finally:
        # Đóng socket proxy sau khi kết thúc
        proxy.close()

if __name__ == "__main__":
    Proxy_Server()
