def calculate_average(numbers):
    total = sum(numbers)
    count = len(numbers)
    average = total / count
    return average


def process_data(raw):
    cleaned = [value * 2 for value in raw if value > 10]
    normalized = [value / max(cleaned) for value in cleaned]
    return cleaned, normalized


def main():
    data = [5, 15, 20, 40, 50]
    cleaned, normalized = process_data(data)
    print("Cleaned:", cleaned)
    print("Normalized:", normalized)

    empty_avg = calculate_average([])
    print("Average:", empty_avg)


if __name__ == "__main__":
    main()
