// sample_poly.cpp — polymorphism test case
#include <cstdio>

class Shape {
public:
    virtual double area() = 0;
    virtual void describe() { printf("Shape\n"); }
};

class Circle : public Shape {
    double radius_;
public:
    explicit Circle(double r) : radius_(r) {}
    double area() override { return 3.14159 * radius_ * radius_; }
    void describe() override { printf("Circle r=%.2f\n", radius_); }
};

class Rectangle : public Shape {
    double w_, h_;
public:
    Rectangle(double w, double h) : w_(w), h_(h) {}
    double area() override { return w_ * h_; }
};

void report(Shape* s) {
    double a = s->area();
    s->describe();
    printf("area=%.2f\n", a);
}

int main() {
    Circle c(3.0);
    Rectangle r(4.0, 5.0);
    report(&c);
    report(&r);
    return 0;
}
