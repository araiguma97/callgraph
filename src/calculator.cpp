// calculator.cpp - C++ class using C utilities
#include <cstdio>

// Forward declarations of C functions
extern "C" {
    int add(int a, int b);
    int subtract(int a, int b);
}

namespace calc {

class Calculator {
public:
    Calculator() : value_(0) {}

    void set(int v) {
        value_ = v;
    }

    int multiply(int x) {
        int result = 0;
        for (int i = 0; i < x; i++) {
            result = add(result, value_);
        }
        return result;
    }

    int sub_from(int x) {
        return subtract(x, value_);
    }

private:
    int value_;
};

} // namespace calc

void print_result(int value) {
    printf("Result: %d\n", value);
}

int main() {
    calc::Calculator c;
    c.set(3);
    print_result(c.multiply(4));
    print_result(c.sub_from(10));
    return 0;
}
