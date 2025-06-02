import requests
base_url = "https://wr8tnxv4f3.execute-api.ap-northeast-1.amazonaws.com/progress/latest/interval?hours=1"
leetcode_data = requests.get(base_url, timeout=10).json()["data"]
user_ids_to_include = ["johnson684", "erictsai90", "dasbd72", "Aron9185"]

big_json_list_comprehension = [
    {
        "time": time_key,
        "users": {
            user_id: time_data.get(user_id) # 使用 .get() 避免 KeyError，如果用戶不存在則返回 None
            for user_id in user_ids_to_include
        }
    }
    for time_key, time_data in leetcode_data.items()
]

print(big_json_list_comprehension)
    
