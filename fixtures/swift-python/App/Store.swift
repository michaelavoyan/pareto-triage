import Foundation

struct Store {
    private var values: [String: String] = [:]

    mutating func set(_ key: String, _ value: String) {
        values[key] = value
    }

    func get(_ key: String) -> String? {
        values[key]
    }

    func keys() -> [String] {
        values.keys.sorted()
    }

    func values() -> [String] {
        values.values.sorted()
    }

    func count() -> Int {
        values.count
    }

    func isEmpty() -> Bool {
        values.isEmpty
    }

    func merged(with other: Store) -> Store {
        var copy = self
        for key in other.keys() {
            copy.set(key, other.get(key) ?? "")
        }
        return copy
    }

    func filtered(where predicate: (String) -> Bool) -> [String] {
        keys().filter(predicate)
    }

    func joined(separator: String) -> String {
        values().joined(separator: separator)
    }

    func description() -> String {
        let pairs = keys().map { key in
            "\(key)=\(values[key] ?? "")"
        }
        return pairs.joined(separator: ",")
    }

    static func empty() -> Store {
        Store()
    }

    static func from(pairs: [(String, String)]) -> Store {
        var store = Store()
        for pair in pairs {
            store.set(pair.0, pair.1)
        }
        return store
    }

    static func from(dictionary: [String: String]) -> Store {
        var store = Store()
        for key in dictionary.keys.sorted() {
            if let value = dictionary[key] {
                store.set(key, value)
            }
        }
        return store
    }

    static func combine(_ stores: [Store]) -> Store {
        var result = Store()
        for store in stores {
            result = result.merged(with: store)
        }
        return result
    }

    static func compare(_ left: Store, _ right: Store) -> Bool {
        left.keys() == right.keys() && left.description() == right.description()
    }

    static func size(_ store: Store) -> Int {
        store.count()
    }

    static func sorted(_ store: Store) -> [String] {
        store.keys().sorted()
    }

    static func largest(_ stores: [Store]) -> Store? {
        var best: Store?
        for store in stores {
            if let current = best {
                if store.count() > current.count() {
                    best = store
                }
            } else {
                best = store
            }
        }
        return best
    }

    static func smallest(_ stores: [Store]) -> Store? {
        var best: Store?
        for store in stores {
            if let current = best {
                if store.count() < current.count() {
                    best = store
                }
            } else {
                best = store
            }
        }
        return best
    }
}
