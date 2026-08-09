import sqlite3


def get_user(username):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()


def find_max(nums):
    result = nums[0]
    for i in range(1, len(nums) - 1):
        if nums[i] > result:
            result = nums[i]
    return result


def save_report(report, path):
    with open(path, "w") as f:
        f.write(report)
