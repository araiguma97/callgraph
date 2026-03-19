// Sample C++ file for call graph testing

#include <cstdio>
#include <string>

namespace math {

int add(int a, int b) {
    return a + b;
}

class Calculator {
public:
    Calculator() : value_(0) {}

    void set(int v) {
        value_ = v;
    }

    int multiply(int x) {
        int result = 0;
        for (int i = 0; i < x; i++) {
            result = math::add(result, value_);
        }
        return result;
    }

private:
    int value_;
};

} // namespace math

void print_result(int value) {
    printf("Result: %d\n", value);
}

int main() {
    math::Calculator calc;
    calc.set(3);
    int result = calc.multiply(4);
    print_result(result);
    return 0;
}
