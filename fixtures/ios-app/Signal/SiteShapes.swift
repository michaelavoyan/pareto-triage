import Foundation

@MainActor
final class SiteShapes {
    private var cache: [String: String] = [:]

    init(cache: [String: String] = [:]) {
        self.cache = cache
        self.storedSummary = "\(cache.count) entries"
    }

    deinit {
        cache.removeAll()
    }

    var summary: String {
        "\(cache.count) cached {entries}"
    }

    var storedSummary: String = "stored"

    @discardableResult
    func render(_ items: [String], template: String = #"{"item": "\(items.count)"}"#) -> String {
        items.map { item in
            "\(template) {\(item)}"
        }.joined(separator: "\n")
    }

    func wrapped() -> [Int] = [
        1,
        2,
    ]
}
