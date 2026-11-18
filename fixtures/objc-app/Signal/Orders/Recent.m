#import "Helpers/Dates.h"

@implementation Recent

- (NSString *)describe:(NSDate *)date {
    return [[Dates new] format:date];
}

@end
