import Foundation

struct OrderCache {
    static let shared = OrderCache()
    private var orders: [String] = []
}
