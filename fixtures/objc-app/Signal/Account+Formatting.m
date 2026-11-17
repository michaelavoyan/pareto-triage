#import "Account+Formatting.h"
#import "Account.h"

@implementation Account (Formatting)

- (NSString *)displayName {
    return self.identifier;
}

@end
