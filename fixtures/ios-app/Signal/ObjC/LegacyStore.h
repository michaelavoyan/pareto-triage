#import <Foundation/Foundation.h>

@interface LegacyStore : NSObject

- (void)store:(NSString *)value completion:(void (^)(BOOL ok))completion;

@end
