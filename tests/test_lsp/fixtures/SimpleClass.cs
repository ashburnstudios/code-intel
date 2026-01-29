namespace SampleProject;

/// <summary>
/// A simple class with direct method calls for basic testing.
/// </summary>
public class SimpleClass
{
    private int _counter;

    public SimpleClass()
    {
        _counter = 0;
    }

    /// <summary>
    /// Public method that calls a private helper.
    /// </summary>
    public void PublicMethod()
    {
        IncrementCounter();
        HelperMethod("called from PublicMethod");
    }

    /// <summary>
    /// Another public method.
    /// </summary>
    public int GetCounter()
    {
        return _counter;
    }

    private void IncrementCounter()
    {
        _counter++;
    }

    private void HelperMethod(string message)
    {
        Console.WriteLine(message);
    }
}

/// <summary>
/// Class that uses SimpleClass.
/// </summary>
public class SimpleClassUser
{
    public void UseSimpleClass()
    {
        var simple = new SimpleClass();
        simple.PublicMethod();
        var count = simple.GetCounter();
        Console.WriteLine($"Count: {count}");
    }
}
